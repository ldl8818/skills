# 新机引导

这里只保存 V3 第一阶段 POSIX Shell 引导和测试；客户端安装、配置与状态由已有 dotfiles 的 `bin/restore setup` 承担。

- 不要求预装 Python，不恢复旧迁移框架。
- 测试通过 source 函数替换系统调用；生产入口不提供切换系统安装目标的环境变量。
- 公开内容仅使用合成值；真实清单保存在用户私有目录。
- 验证：`/bin/sh -n bootstrap/setup.command`，`python3 -m unittest discover -s tests`。系统安装须另行实机验证。
