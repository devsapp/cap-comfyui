from vision_plaid.comfy.v1.base_nodes import DiffusionBoostV1Node, ParallelKSampler, ParallelKSamplerAdvanced

from .loader_nodes import LoadDiffusionModel

NODE_CLASS_MAPPINGS = {
    "DiffusionBoostV1": DiffusionBoostV1Node,
    "LoadDiffusionModel": LoadDiffusionModel,
    "ParallelKSampler": ParallelKSampler,
    "ParallelKSamplerAdvanced": ParallelKSamplerAdvanced,
}


NODE_DISPLAY_NAME_MAPPINGS = {
    "DiffusionBoostV1": "🚀 Diffusion Boost V1",
    "LoadDiffusionModel": "VisionPlaid Load Diffusion Model",
    "ParallelKSampler": "🚀 Parallel KSampler",
    "ParallelKSamplerAdvanced": "🚀 Parallel KSampler Advanced",
}
