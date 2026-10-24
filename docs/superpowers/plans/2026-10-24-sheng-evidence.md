# sheng 官方构建输入补齐计划

目标：生成真实 QEMU 运行证据和卷签名策略，保持完整 sheng 功能，最终生成镜像并实机验证。
约束：不伪造审计 JSON、不跳过 root 验证；先虚拟机，设备写入前确认实际准备条件。

- [ ] 编译最小原生 4K 候选，保留真实 prelink 计划和编译记录。
- [ ] 构建 UniXNU/DarwinBoot EFI，兼容旧调试脚本路径。
- [ ] QEMU 到达 bsd_init，采集存储/AES 元类与 MMU 寄存器。
- [ ] 获取固定哈希 KDK 注释文件，运行官方 AES 和 storage 审计。
- [ ] 生成 owner 密钥、主机验证库及真实 OS/SystemOS 签名策略。
- [ ] 补齐显示、GPU、触控构建输入，恢复完整 sheng_defconfig 构建。
- [ ] 生成启动镜像与 userdata，校验容量、哈希和回退条件。
- [ ] 需要用户操作时再请求，设备启动后验证实际行为，不能以 CI 绿色代替完成。

当前已复现官方 macOS build run 40079785988 的 archive10 缺 storage audit。
先在独立分支 sheng-evidence 执行前两步及最小运行验证，不修改主分支。
