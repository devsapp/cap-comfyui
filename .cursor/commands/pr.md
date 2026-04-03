# 提交 PR

当用户执行此命令时，请按以下流程操作：

## 第一步：分析当前更改

并行执行以下命令获取完整信息：
- `git status` - 查看所有未跟踪和已修改的文件
- `git diff HEAD` - 查看所有更改的具体内容（包括已暂存和未暂存）
- `git log --oneline -5` - 查看最近的 commit 记录
- `git branch --show-current` - 获取当前分支名

## 第二步：智能生成 Commit Message

根据更改内容，生成一个精简的 commit message：

### 判断类型规则：
- **feat:** 新增功能、新增文件、添加新特性
- **fix:** 修复 bug、错误处理、问题修复
- **docs:** 仅文档更改
- **refactor:** 重构代码但不改变功能
- **test:** 添加或修改测试
- **chore:** 配置文件、依赖更新等

### Message 格式要求：
- 使用中文描述
- 简洁明了，一句话概括核心变更
- 如果有多个文件/模块的更改，概括主要目的
- 示例：
  - `feat: 添加快照管理器功能`
  - `fix: 修复任务队列满时的错误处理`
  - `refactor: 重构 serverless handler 架构`

## 第三步：执行 Git 操作

按顺序执行：

1. **暂存所有更改**：
   ```bash
   git add .
   ```

2. **提交更改**（使用 HEREDOC 格式）：
   ```bash
   git commit -m "$(cat <<'EOF'
[生成的 commit message]
EOF
)"
   ```

3. **Push 到远程分支**：
   ```bash
   git push -u origin HEAD
   ```

## 第四步：创建 Pull Request

使用 `gh` CLI 创建 PR：

```bash
gh pr create --title "[生成的 commit message]" --body "$(cat <<'EOF'
## 变更摘要
[根据 git diff 生成 2-3 个要点]

## 变更类型
- [ ] 新功能
- [ ] Bug 修复
- [ ] 重构
- [ ] 文档更新
- [ ] 其他

## 测试
- [ ] 已通过本地测试
- [ ] 已验证功能正常

EOF
)"
```

## 第五步：返回结果

从 `gh pr create` 命令的输出中提取 PR URL（通常在命令执行成功后会返回 PR 链接）。

向用户清晰展示：

```
✅ PR 创建成功！

📝 Commit Message: [生成的 commit message]

🔗 PR 链接: [从 gh pr create 输出中提取的完整 URL]

分支: [当前分支名] → main
```

**重要提示**：
- 必须显示完整的 PR URL（例如：https://github.com/devsapp/cap-comfyui/pull/123）
- PR URL 应该是可点击的链接
- 如果 gh 命令返回错误，清晰报告给用户

## 注意事项

- 如果当前没有任何更改（git status clean），提示用户没有可提交的内容
- 如果 git push 失败，提示用户检查远程分支权限
- 如果 gh 命令不可用，提示用户安装 GitHub CLI
- 如果当前分支是 main/master，警告用户不应直接提交到主分支
- 所有错误都应清晰地报告给用户