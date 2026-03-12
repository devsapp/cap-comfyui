import comfy.ops as cops
import torch
import torch.nn.functional as F
from comfy.ops import cast_bias_weight, manual_cast

import vision_plaid.comfy.ops as vpops
from vision_plaid.linear.quant import QuantizedLinear


class FP8Quant(manual_cast):
    do_upcast = True  # fp8 model weights need this

    class Linear(manual_cast.Linear):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.scale_weight = None
            self.scale_input = None
            self.weight_scale = None
            self.quantized_weight = None

        def reset_parameters(self):
            self.scale_weight = None
            self.scale_input = None
            self.weight_scale = None
            self.quantized_weight = None
            return None

        def forward_comfy_cast_weights(self, input):
            if QuantizedLinear.use_activation_scale or (QuantizedLinear.use_weight_scale and not FP8Quant.do_upcast):
                out = vpops.fp8_linear(self, input)
            else:
                out = cops.fp8_linear(self, input)
            if out is not None:
                return out

            assert self.weight.device == input.device
            weight, bias = cast_bias_weight(self, input) if FP8Quant.do_upcast else (self.weight, self.bias)
            return torch.nn.functional.linear(input, weight, bias)
