import unittest

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper

import modules.onnx_optimize as onnx_optimize


def make_reflect_pad_model(pad: int):
    input_value = helper.make_tensor_value_info(
        "input", TensorProto.FLOAT, [1, 1, 4, 4]
    )
    output_value = helper.make_tensor_value_info(
        "output", TensorProto.FLOAT, [1, 1, 4 + 2 * pad, 4 + 2 * pad]
    )
    pads = numpy_helper.from_array(
        np.array([0, 0, pad, pad, 0, 0, pad, pad], dtype=np.int64),
        name="pads",
    )
    node = helper.make_node(
        "Pad",
        inputs=["input", "pads"],
        outputs=["output"],
        mode="reflect",
    )
    graph = helper.make_graph(
        [node],
        "reflect-pad-test",
        [input_value],
        [output_value],
        [pads],
    )
    return helper.make_model(graph)


class OnnxSecurityLimitTests(unittest.TestCase):
    def test_reflect_pad_decomposition_allows_small_pads(self):
        model = make_reflect_pad_model(4)

        self.assertTrue(onnx_optimize._decompose_reflect_pad(model))

    def test_reflect_pad_decomposition_rejects_large_pads(self):
        model = make_reflect_pad_model(65)

        with self.assertRaises(ValueError):
            onnx_optimize._decompose_reflect_pad(model)


if __name__ == "__main__":
    unittest.main()
