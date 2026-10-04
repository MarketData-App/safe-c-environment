import os
import lit_bridge

config.name = 'C safety qualification'
config.test_format = lit_bridge.GateFormat(lit_bridge.Q)
config.suffixes = ['.test']
config.test_source_root = os.path.dirname(__file__)
config.test_exec_root = lit_bridge.OUTPUT
