"""
将 models_xxx.json 融入 models.json（主模型列表）

规则:
  - 新模型直接追加到 models.json
  - 已存在的模型跳过（不覆盖）

用法:
  python3 merge_models.py <source.json> [models.json]
"""

import json
import sys
import os


def merge(source_path: str, target_path: str) -> None:
    if not os.path.exists(source_path):
        print(f"错误: 源文件不存在: {source_path}")
        sys.exit(1)

    if not os.path.exists(target_path):
        print(f"错误: 目标文件不存在: {target_path}")
        sys.exit(1)

    with open(source_path, "r", encoding="utf-8") as f:
        source: dict = json.load(f)

    with open(target_path, "r", encoding="utf-8") as f:
        target: dict = json.load(f)

    added = []
    skipped = []

    for name, info in source.items():
        if name in target:
            skipped.append(name)
        else:
            target[name] = info
            added.append(name)

    with open(target_path, "w", encoding="utf-8") as f:
        json.dump(target, f, indent=2, ensure_ascii=False)

    os.remove(source_path)

    print(f"源文件:   {source_path}  ({len(source)} 个模型)")
    print(f"目标文件: {target_path}")
    print()

    if added:
        print(f"新增 {len(added)} 个模型:")
        for name in added:
            print(f"  + {name}")
    else:
        print("无新增模型")

    if skipped:
        print(f"\n跳过 {len(skipped)} 个已存在的模型:")
        for name in skipped:
            print(f"  ~ {name}")

    print(f"\n完成。models.json 现有 {len(target)} 个模型。")
    print(f"已删除源文件: {source_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2 or len(sys.argv) > 3:
        print(f"用法: python3 {sys.argv[0]} <source.json> [models.json]")
        print()
        print("示例:")
        print(f"  python3 {sys.argv[0]} models_20260308.json")
        print(f"  python3 {sys.argv[0]} models_nunchaku.json models.json")
        sys.exit(1)

    source_path = sys.argv[1]
    # 默认目标为同目录下的 models.json
    default_target = os.path.join(os.path.dirname(os.path.abspath(source_path)), "models.json")
    target_path = sys.argv[2] if len(sys.argv) == 3 else default_target

    merge(source_path, target_path)
