import json
import logging
import os

import comfy
import folder_paths
import torch
from comfy import model_detection, model_management

from vision_plaid.comfy.v1.common import VPModel, VisionPlaidPluginState, get_model_config, register_on_clone_callback
from vision_plaid.comfy.v1.qwen_image_wrapper import VPModelPatcher


from .ops import FP8Quant


def check_hardware_compatibility(quantization_config: dict, device: str | torch.device = "cuda"):
    """
    Check if the quantization config is compatible with the current GPU.

    Parameters
    ----------
    quantization_config : dict
        Quantization configuration dictionary.
    device : str or torch.device, optional
        Device to check (default: "cuda").

    Raises
    ------
    ValueError
        If the quantization config is not compatible with the GPU architecture.
    """
    if isinstance(device, str):
        device = torch.device(device)
    capability = torch.cuda.get_device_capability(0 if device.index is None else device.index)
    sm = f"{capability[0]}{capability[1]}"
    if sm in ["120", "121"]:  # you can only use the fp4 models
        if quantization_config["weight"]["dtype"] != "fp4_e2m1_all":
            raise ValueError('Please use "fp4" quantization for Blackwell GPUs. ')
    elif sm in ["75", "80", "86", "89"]:
        if quantization_config["weight"]["dtype"] != "int4":
            raise ValueError('Please use "int4" quantization for Turing, Ampere and Ada GPUs. ')
    else:
        raise ValueError(
            f"Unsupported GPU architecture {sm} due to the lack of 4-bit tensorcores. "
            "Please use a Turing, Ampere, Ada or Blackwell GPU for this quantization configuration."
        )


def get_precision_from_quantization_config(quantization_config: dict) -> str:
    """
    Get the precision from the quantization configuration.
    """
    if quantization_config["weight"]["dtype"] == "fp4_e2m1_all":
        if quantization_config["weight"]["group_size"] == 16:
            return "nvfp4"
        else:
            raise ValueError("Currently, nunchaku only supports nvfp4.")
    elif quantization_config["weight"]["dtype"] == "int4":
        return "int4"
    else:
        raise ValueError(f"Unsupported quantization dtype: {quantization_config['weight']['dtype']}")


# Based on ComfyUI version v0.3.76
def load_diffusion_model_state_dict(sd, model_options={}, metadata=None, vp_config={}):
    dtype = model_options.get("dtype", None)

    # Allow loading unets from checkpoint files
    diffusion_model_prefix = model_detection.unet_prefix_from_state_dict(sd)
    temp_sd = comfy.utils.state_dict_prefix_replace(sd, {diffusion_model_prefix: ""}, filter_keys=True)
    if len(temp_sd) > 0:
        sd = temp_sd

    parameters = comfy.utils.calculate_parameters(sd)
    weight_dtype = comfy.utils.weight_dtype(sd)

    load_device = model_management.get_torch_device()

    if vp_config.get("w4a4", False):
        try:
            quantization_config = json.loads(metadata.get("quantization_config", "{}"))
            vp_config["quant_dtype"] = get_precision_from_quantization_config(quantization_config)
            check_hardware_compatibility(quantization_config, load_device)
            model_config = get_model_config(sd, "", metadata=metadata, vp_config=vp_config)
            assert not model_options.get("fp8_optimizations", False)
        except:
            import traceback

            logging.warning("not w4a4 weights")
            print(traceback.format_exc())
            return None
    else:
        model_config = get_model_config(sd, "", metadata=metadata)
        if model_config is None:
            model_config = model_detection.model_config_from_unet(sd, "", metadata=metadata)

    if model_config is not None:
        new_sd = sd
    else:
        new_sd = model_detection.convert_diffusers_mmdit(sd, "")
        if new_sd is not None:  # diffusers mmdit
            model_config = model_detection.model_config_from_unet(new_sd, "")
            if model_config is None:
                return None
        else:  # diffusers unet
            model_config = model_detection.model_config_from_diffusers_unet(sd)
            if model_config is None:
                return None

            diffusers_keys = comfy.utils.unet_to_diffusers(model_config.unet_config)

            new_sd = {}
            for k in diffusers_keys:
                if k in sd:
                    new_sd[diffusers_keys[k]] = sd.pop(k)
                else:
                    logging.warning("{} {}".format(diffusers_keys[k], k))

    offload_device = model_management.unet_offload_device()
    unet_weight_dtype = list(model_config.supported_inference_dtypes)
    if model_config.scaled_fp8 is not None:
        weight_dtype = None

    if dtype is None:
        unet_dtype = model_management.unet_dtype(
            model_params=parameters, supported_dtypes=unet_weight_dtype, weight_dtype=weight_dtype
        )
    else:
        unet_dtype = dtype

    if model_config.layer_quant_config is not None:
        manual_cast_dtype = model_management.unet_manual_cast(
            None, load_device, model_config.supported_inference_dtypes
        )
    else:
        manual_cast_dtype = model_management.unet_manual_cast(
            unet_dtype, load_device, model_config.supported_inference_dtypes
        )
    model_config.set_inference_dtype(unet_dtype, manual_cast_dtype)
    model_config.custom_operations = model_options.get("custom_operations", model_config.custom_operations)
    if model_options.get("fp8_optimizations", False):
        model_config.optimizations["fp8"] = True

    model = model_config.get_model(new_sd, "")
    model = model.to(offload_device)
    if not isinstance(model, VPModel):
        model.load_model_weights(new_sd, "")
        left_over = sd.keys()
        if len(left_over) > 0:
            logging.info("left over keys in diffusion model: {}".format(left_over))
        return comfy.model_patcher.ModelPatcher(model, load_device=load_device, offload_device=offload_device)
    else:
        model.load_model_weights(new_sd, "", quant_dtype=vp_config.get("quant_dtype", None))
        model.patch_model()
        return VPModelPatcher(model, load_device=load_device, offload_device=offload_device)


def model_detection_error_hint(path, state_dict):
    filename = os.path.basename(path)
    if "lora" in filename.lower():
        return "\nHINT: This seems to be a Lora file and Lora files should be put in the lora folder and loaded with a lora loader node.."
    return ""


def load_diffusion_model(unet_path, model_options={}, vp_config={}):
    sd, metadata = comfy.utils.load_torch_file(unet_path, return_metadata=True)
    model = load_diffusion_model_state_dict(sd, model_options=model_options, metadata=metadata, vp_config=vp_config)
    if model is None:
        logging.error("ERROR UNSUPPORTED DIFFUSION MODEL {}".format(unet_path))
        raise RuntimeError(
            "ERROR: Could not detect model type of: {}\n{}".format(unet_path, model_detection_error_hint(unet_path, sd))
        )
    return model


class LoadDiffusionModel:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "unet_name": (folder_paths.get_filename_list("diffusion_models"),),
                "weight_dtype": (["default", "int4", "nvfp4", "fp8_e4m3fn", "fp8_e4m3fn_fast", "fp8_e5m2"],),
            }
        }

    RETURN_TYPES = ("MODEL",)
    FUNCTION = "load_unet"

    CATEGORY = "VisionPlaid"

    def load_unet(self, unet_name, weight_dtype):
        model_options = {}
        vp_config = {}
        if weight_dtype == "int4" or weight_dtype == "nvfp4":
            vp_config["w4a4"] = True
            vp_config["unet_name"] = unet_name
        elif weight_dtype == "fp8_e4m3fn":
            model_options["dtype"] = torch.float8_e4m3fn
        elif weight_dtype == "fp8_e4m3fn_fast":
            model_options["dtype"] = torch.float8_e4m3fn
            model_options["fp8_optimizations"] = True
        elif weight_dtype == "fp8_e5m2":
            model_options["dtype"] = torch.float8_e5m2

        unet_path = folder_paths.get_full_path_or_raise("diffusion_models", unet_name)
        model = load_diffusion_model(unet_path, model_options=model_options, vp_config=vp_config)
        if not hasattr(model, "vp_state"):
            model.vp_state = VisionPlaidPluginState()
        if vp_config.get("w4a4", False):
            model.vp_state.w4a4_weights = vp_config["unet_name"]
            model.vp_state.enable_quant = True
            model.vp_state.quant_dtype = vp_config["quant_dtype"]
        model = register_on_clone_callback(model)
        return (model,)
