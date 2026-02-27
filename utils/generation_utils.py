# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Utility functions for interacting with Gemini and Claude APIs, image processing, and PDF handling.
"""

import json
import asyncio
import base64
from io import BytesIO
from functools import partial
from ast import literal_eval
from typing import List, Dict, Any

import aiofiles
from PIL import Image
from google import genai
from google.genai import types
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

import os

import yaml
from pathlib import Path

# Load config
config_path = Path(__file__).parent.parent / "configs" / "model_config.yaml"
model_config = {}
if config_path.exists():
    with open(config_path, "r") as f:
        model_config = yaml.safe_load(f) or {}

def get_config_val(section, key, env_var, default=""):
    val = os.getenv(env_var)
    if not val and section in model_config:
        val = model_config[section].get(key)
    return val or default

# Initialize clients lazily or with robust defaults
api_key = get_config_val("api_keys", "google_api_key", "GOOGLE_API_KEY", "")
google_base_url = get_config_val("api_base_urls", "google_base_url", "GOOGLE_BASE_URL", "")
if api_key:
    gemini_kwargs = {"api_key": api_key}
    http_opts = {}
    if google_base_url:
        raw_api_version = model_config.get("api_base_urls", {}).get("google_api_version")
        if raw_api_version is None:
            raw_api_version = os.getenv("GOOGLE_API_VERSION")
        http_opts["base_url"] = google_base_url
        if raw_api_version is not None:
            http_opts["api_version"] = raw_api_version
    env_proxy = os.getenv("https_proxy") or os.getenv("HTTPS_PROXY") or os.getenv("http_proxy") or os.getenv("HTTP_PROXY")
    if env_proxy:
        http_opts["client_args"] = {"proxy": env_proxy}
        http_opts["async_client_args"] = {"proxy": env_proxy}
    if http_opts:
        gemini_kwargs["http_options"] = types.HttpOptions(**http_opts)
    gemini_client = genai.Client(**gemini_kwargs)
    print(f"Initialized Gemini Client with API Key" + (f" (base_url: {google_base_url})" if google_base_url else "") + (f" (proxy: {env_proxy})" if env_proxy else ""))
else:
    print("Warning: Could not initialize Gemini Client. Missing credentials.")
    gemini_client = None


anthropic_api_key = get_config_val("api_keys", "anthropic_api_key", "ANTHROPIC_API_KEY", "")
anthropic_base_url = get_config_val("api_base_urls", "anthropic_base_url", "ANTHROPIC_BASE_URL", "")
if anthropic_api_key:
    anthropic_kwargs = {"api_key": anthropic_api_key}
    if anthropic_base_url:
        anthropic_kwargs["base_url"] = anthropic_base_url
    anthropic_client = AsyncAnthropic(**anthropic_kwargs)
    print(f"Initialized Anthropic Client with API Key" + (f" (base_url: {anthropic_base_url})" if anthropic_base_url else ""))
else:
    print("Warning: Could not initialize Anthropic Client. Missing credentials.")
    anthropic_client = None

openai_api_key = get_config_val("api_keys", "openai_api_key", "OPENAI_API_KEY", "")
openai_base_url = get_config_val("api_base_urls", "openai_base_url", "OPENAI_BASE_URL", "")
if openai_api_key:
    openai_kwargs = {"api_key": openai_api_key}
    if openai_base_url:
        openai_kwargs["base_url"] = openai_base_url
    openai_client = AsyncOpenAI(**openai_kwargs)
    print(f"Initialized OpenAI Client with API Key" + (f" (base_url: {openai_base_url})" if openai_base_url else ""))
else:
    print("Warning: Could not initialize OpenAI Client. Missing credentials.")
    openai_client = None



def _convert_to_gemini_parts(contents: List[Dict[str, Any]]) -> List[types.Part]:
    """
    Convert a generic content list to a list of Gemini's genai.types.Part objects.
    """
    gemini_parts = []
    for item in contents:
        if item.get("type") == "text":
            gemini_parts.append(types.Part.from_text(text=item["text"]))
        elif item.get("type") == "image":
            source = item.get("source", {})
            if source.get("type") == "base64":
                gemini_parts.append(
                    types.Part.from_bytes(
                        data=base64.b64decode(source["data"]),
                        mime_type=source["media_type"],
                    )
                )
    return gemini_parts


async def call_gemini_with_retry_async(
    model_name, contents, config, max_attempts=5, retry_delay=5, error_context=""
):
    """
    ASYNC: Call Gemini API with asynchronous retry logic.
    """
    if gemini_client is None:
        raise RuntimeError(
            "Gemini client was not initialized: missing Google API key. "
            "Please set GOOGLE_API_KEY in environment, or configure api_keys.google_api_key in configs/model_config.yaml."
        )

    result_list = []
    target_candidate_count = config.candidate_count
    # Gemini API max candidate count is 8. We will call multiple times if needed.
    if config.candidate_count > 8:
        config.candidate_count = 8

    current_contents = contents
    for attempt in range(max_attempts):
        try:
            # Use global client
            client = gemini_client

            # Convert generic content list to Gemini's format right before the API call
            gemini_contents = _convert_to_gemini_parts(current_contents)
            response = await client.aio.models.generate_content(
                model=model_name, contents=gemini_contents, config=config
            )

            # If we are using Image Generation models to generate images
            if (
                "nanoviz" in model_name
                or "image" in model_name
            ):
                raw_response_list = []
                if not response.candidates or not response.candidates[0].content.parts:
                    print(
                        f"[Warning]: Failed to generate image, retrying in {retry_delay} seconds..."
                    )
                    await asyncio.sleep(retry_delay)
                    continue

                # In this mode, we can only have one candidate
                for part in response.candidates[0].content.parts:
                    if part.inline_data:
                        # Append base64 encoded image data to raw_response_list
                        raw_response_list.append(
                            base64.b64encode(part.inline_data.data).decode("utf-8")
                        )
                        break

            # Otherwise, for text generation models
            else:
                raw_response_list = [
                    part.text
                    for candidate in response.candidates
                    for part in candidate.content.parts
                ]
            result_list.extend([r for r in raw_response_list if r.strip() != ""])
            if len(result_list) >= target_candidate_count:
                result_list = result_list[:target_candidate_count]
                break

        except Exception as e:
            context_msg = f" for {error_context}" if error_context else ""
            current_delay = min(retry_delay * (2 ** attempt), 30)
            err_msg = str(e) or type(e).__name__
            print(
                f"Attempt {attempt + 1} for model {model_name} failed{context_msg}: {err_msg}. Retrying in {current_delay} seconds..."
            )

            if attempt < max_attempts - 1:
                await asyncio.sleep(current_delay)
            else:
                print(f"Error: All {max_attempts} attempts failed{context_msg}")
                result_list = ["Error"] * target_candidate_count

    if len(result_list) < target_candidate_count:
        result_list.extend(["Error"] * (target_candidate_count - len(result_list)))
    return result_list

def _convert_to_claude_format(contents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Converts the generic content list to Claude's API format.
    Currently, the formats are identical, so this acts as a pass-through
    for architectural consistency and future-proofing.

    Claude API's format:
    [
        {"type": "text", "text": "some text"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "..."}},
        ...
    ]
    """
    return contents


def _convert_to_openai_format(contents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Converts the generic content list (Claude format) to OpenAI's API format.
    
    Claude format:
    [
        {"type": "text", "text": "some text"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "..."}},
        ...
    ]
    
    OpenAI format:
    [
        {"type": "text", "text": "some text"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}},
        ...
    ]
    """
    openai_contents = []
    for item in contents:
        if item.get("type") == "text":
            openai_contents.append({"type": "text", "text": item["text"]})
        elif item.get("type") == "image":
            source = item.get("source", {})
            if source.get("type") == "base64":
                media_type = source.get("media_type", "image/jpeg")
                data = source.get("data", "")
                # OpenAI expects data URL format
                data_url = f"data:{media_type};base64,{data}"
                openai_contents.append({
                    "type": "image_url",
                    "image_url": {"url": data_url}
                })
    return openai_contents


async def call_claude_with_retry_async(
    model_name, contents, config, max_attempts=5, retry_delay=30, error_context=""
):
    """
    ASYNC: Call Claude API with asynchronous retry logic.
    This version efficiently handles input size errors by validating and modifying
    the content list once before generating all candidates.
    """
    system_prompt = config["system_prompt"]
    temperature = config["temperature"]
    candidate_num = config["candidate_num"]
    max_output_tokens = config["max_output_tokens"]
    response_text_list = []

    # --- Preparation Phase ---
    # Convert to the Claude-specific format and perform an initial optimistic resize.
    current_contents = contents

    # --- Validation and Remediation Phase ---
    # We loop until we get a single successful response, proving the input is valid.
    # Note that this check is required because Claude only has 128k / 256k context windows.
    # For Gemini series that support 1M, we do not need this step.
    is_input_valid = False
    for attempt in range(max_attempts):
        try:
            claude_contents = _convert_to_claude_format(current_contents)
            # Attempt to generate the very first candidate.
            first_response = await anthropic_client.messages.create(
                model=model_name,
                max_tokens=max_output_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": claude_contents}],
                system=system_prompt,
            )
            response_text_list.append(first_response.content[0].text)
            is_input_valid = True
            break

        except Exception as e:
            error_str = str(e).lower()
            context_msg = f" for {error_context}" if error_context else ""
            print(
                f"Validation attempt {attempt + 1} failed{context_msg}: {error_str}. Retrying in {retry_delay} seconds..."
            )
            if attempt < max_attempts - 1:
                await asyncio.sleep(retry_delay)

    # --- Sampling Phase ---
    if not is_input_valid:
        print(
            f"Error: All {max_attempts} attempts failed to validate the input{context_msg}. Returning errors."
        )
        return ["Error"] * candidate_num

    # We already have 1 successful candidate, now generate the rest.
    remaining_candidates = candidate_num - 1
    if remaining_candidates > 0:
        print(
            f"Input validated. Now generating remaining {remaining_candidates} candidates..."
        )
        valid_claude_contents = _convert_to_claude_format(current_contents)
        tasks = [
            anthropic_client.messages.create(
                model=model_name,
                max_tokens=max_output_tokens,
                temperature=temperature,
                messages=[
                    {"role": "user", "content": valid_claude_contents}
                ],
                system=system_prompt,
            )
            for _ in range(remaining_candidates)
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in results:
            if isinstance(res, Exception):
                print(f"Error generating a subsequent candidate: {res}")
                response_text_list.append("Error")
            else:
                response_text_list.append(res.content[0].text)

    return response_text_list

async def call_openai_with_retry_async(
    model_name, contents, config, max_attempts=5, retry_delay=30, error_context=""
):
    """
    ASYNC: Call OpenAI API with asynchronous retry logic.
    This follows the same pattern as Claude's implementation.
    """
    system_prompt = config["system_prompt"]
    temperature = config["temperature"]
    candidate_num = config["candidate_num"]
    max_completion_tokens = config["max_completion_tokens"]
    response_text_list = []

    # --- Preparation Phase ---
    # Convert to the OpenAI-specific format
    current_contents = contents

    # --- Validation and Remediation Phase ---
    # We loop until we get a single successful response, proving the input is valid.
    is_input_valid = False
    for attempt in range(max_attempts):
        try:
            openai_contents = _convert_to_openai_format(current_contents)
            # Attempt to generate the very first candidate.
            first_response = await openai_client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": openai_contents}
                ],
                temperature=temperature,
                max_completion_tokens=max_completion_tokens,
            )
            # If we reach here, the input is valid.
            response_text_list.append(first_response.choices[0].message.content)
            is_input_valid = True
            break  # Exit the validation loop

        except Exception as e:
            error_str = str(e).lower()
            context_msg = f" for {error_context}" if error_context else ""
            print(
                f"Validation attempt {attempt + 1} failed{context_msg}: {error_str}. Retrying in {retry_delay} seconds..."
            )
            if attempt < max_attempts - 1:
                await asyncio.sleep(retry_delay)

    # --- Sampling Phase ---
    if not is_input_valid:
        print(
            f"Error: All {max_attempts} attempts failed to validate the input{context_msg}. Returning errors."
        )
        return ["Error"] * candidate_num

    # We already have 1 successful candidate, now generate the rest.
    remaining_candidates = candidate_num - 1
    if remaining_candidates > 0:
        print(
            f"Input validated. Now generating remaining {remaining_candidates} candidates..."
        )
        valid_openai_contents = _convert_to_openai_format(current_contents)
        tasks = [
            openai_client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": valid_openai_contents}
                ],
                temperature=temperature,
                max_completion_tokens=max_completion_tokens,
            )
            for _ in range(remaining_candidates)
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in results:
            if isinstance(res, Exception):
                print(f"Error generating a subsequent candidate: {res}")
                response_text_list.append("Error")
            else:
                response_text_list.append(res.choices[0].message.content)

    return response_text_list


async def call_openai_image_generation_with_retry_async(
    model_name, prompt, config, max_attempts=5, retry_delay=30, error_context=""
):
    """
    ASYNC: Call OpenAI Image Generation API (GPT-Image) with asynchronous retry logic.
    """
    size = config.get("size", "1536x1024")
    quality = config.get("quality", "high")
    background = config.get("background", "opaque")
    output_format = config.get("output_format", "png")
    
    # Base parameters for all models
    gen_params = {
        "model": model_name,
        "prompt": prompt,
        "n": 1,
        "size": size,
    }
    
    # Add GPT-Image specific parameters
    gen_params.update({
        "quality": quality,
        "background": background,
        "output_format": output_format,
    })

    for attempt in range(max_attempts):
        try:
            response = await openai_client.images.generate(**gen_params)
            
            # OpenAI images.generate returns a list of images in response.data
            if response.data and response.data[0].b64_json:
                return [response.data[0].b64_json]
            else:
                print(f"[Warning]: Failed to generate image via OpenAI, no data returned.")
                if attempt < max_attempts - 1:
                    await asyncio.sleep(retry_delay)
                continue

        except Exception as e:
            context_msg = f" for {error_context}" if error_context else ""
            print(
                f"Attempt {attempt + 1} for OpenAI image generation model {model_name} failed{context_msg}: {e}. Retrying in {retry_delay} seconds..."
            )

            if attempt < max_attempts - 1:
                await asyncio.sleep(retry_delay)
            else:
                print(f"Error: All {max_attempts} attempts failed{context_msg}")
                return ["Error"]

    return ["Error"]


_text_provider_override = get_config_val("provider_override", "text_model_provider", "TEXT_MODEL_PROVIDER", "")
_image_provider_override = get_config_val("provider_override", "image_model_provider", "IMAGE_MODEL_PROVIDER", "")

def _infer_provider(model_name: str, is_image: bool = False) -> str:
    """Infer API provider from model name, with config override support.
    Override via provider_override.text_model_provider / image_model_provider in config.
    Auto-detection: 'gemini' → google, 'claude' → anthropic, others → openai.
    """
    override = _image_provider_override if is_image else _text_provider_override
    if override:
        normalized = override.lower().strip()
        if normalized in ("google", "gemini"):
            return "gemini"
        if normalized in ("anthropic", "claude"):
            return "anthropic"
        if normalized in ("openai",):
            return "openai"

    name = model_name.lower()
    if "gemini" in name:
        return "gemini"
    if "claude" in name:
        return "anthropic"
    return "openai"


async def call_text_model_with_retry_async(
    model_name: str,
    contents: List[Dict[str, Any]],
    system_prompt: str = "",
    temperature: float = 1.0,
    candidate_count: int = 1,
    max_output_tokens: int = 50000,
    max_attempts: int = 5,
    retry_delay: int = 5,
    error_context: str = "",
) -> List[str]:
    """
    Unified text-generation dispatch. Routes to Gemini, Claude, or OpenAI
    based on model_name. Accepts contents in the standard format:
      [{"type": "text", "text": "..."}, {"type": "image", "source": {...}}, ...]
    """
    provider = _infer_provider(model_name)

    if provider == "gemini":
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=temperature,
            candidate_count=candidate_count,
            max_output_tokens=max_output_tokens,
        )
        return await call_gemini_with_retry_async(
            model_name, contents, config, max_attempts, retry_delay, error_context
        )

    elif provider == "anthropic":
        if anthropic_client is None:
            raise RuntimeError(
                "Anthropic client was not initialized: missing API key. "
                "Please set ANTHROPIC_API_KEY or configure api_keys.anthropic_api_key in configs/model_config.yaml."
            )
        config = {
            "system_prompt": system_prompt,
            "temperature": temperature,
            "candidate_num": candidate_count,
            "max_output_tokens": max_output_tokens,
        }
        return await call_claude_with_retry_async(
            model_name, contents, config, max_attempts, retry_delay, error_context
        )

    else:  # openai (default — works with any OpenAI-compatible API)
        if openai_client is None:
            raise RuntimeError(
                "OpenAI client was not initialized: missing API key. "
                "Please set OPENAI_API_KEY or configure api_keys.openai_api_key in configs/model_config.yaml."
            )
        config = {
            "system_prompt": system_prompt,
            "temperature": temperature,
            "candidate_num": candidate_count,
            "max_completion_tokens": max_output_tokens,
        }
        return await call_openai_with_retry_async(
            model_name, contents, config, max_attempts, retry_delay, error_context
        )
