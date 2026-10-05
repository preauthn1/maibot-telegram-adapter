"""静态元数据回归用例；不导入或执行插件（由父 Agent 授权后验收）。"""

from pathlib import Path
from tempfile import TemporaryDirectory

import unittest

from .static_metadata import read_static_plugin_schema


class StaticMetadataTests(unittest.TestCase):
    def test_literals_metadata_and_password_defaults(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "plugin.py").write_text(
                "from .config import Settings\nclass Plugin:\n    config_model = Settings\n",
                encoding="utf-8",
            )
            (root / "constants.py").write_text("DELAY = 0.8\n", encoding="utf-8")
            (root / "config.py").write_text(
                "from .constants import DELAY\n"
                "raise RuntimeError('禁止执行')\n"
                "class Behavior(PluginConfigBase):\n"
                "    __ui_label__ = '拟人化行为'\n"
                "    delay: float = Field(default=DELAY, ge=0, le=10, "
                "json_schema_extra={'label': '停顿（秒）', 'hidden': True})\n"
                "    secret: str = Field(default='source-secret', "
                "json_schema_extra={'input_type': 'password'})\n"
                "class Settings(PluginConfigBase):\n"
                "    behavior: Behavior = Field(default_factory=Behavior)\n",
                encoding="utf-8",
            )
            schema = read_static_plugin_schema("example", root)
            self.assertIsNotNone(schema)
            fields = schema["sections"]["behavior"]["fields"]
            self.assertEqual(schema["sections"]["behavior"]["title"], "拟人化行为")
            self.assertEqual(fields["delay"]["label"], "停顿（秒）")
            self.assertEqual(fields["delay"]["default"], 0.8)
            self.assertEqual(fields["delay"]["min"], 0)
            self.assertEqual(fields["delay"]["max"], 10)
            self.assertTrue(fields["delay"]["hidden"])
            self.assertNotIn("default", fields["secret"])

    def test_dynamic_factory_is_not_executed_or_guessed(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "plugin.py").write_text(
                "from .config import Settings\nclass Plugin:\n    config_model = Settings\n",
                encoding="utf-8",
            )
            (root / "config.py").write_text(
                "class Section(PluginConfigBase):\n"
                "    value: str = Field(default_factory=connect_to_network)\n"
                "class Settings(PluginConfigBase):\n"
                "    section: Section = Field(default_factory=Section)\n",
                encoding="utf-8",
            )
            self.assertIsNone(read_static_plugin_schema("example", root))
