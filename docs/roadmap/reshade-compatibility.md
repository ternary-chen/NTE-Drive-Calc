# 已安装 ReShade 的玩家与计算器共存

## 范围与状态

目标是保留玩家自行安装的 ReShade，使原生同步、战报和 HUD 能与其共存。
不捆绑 ReShade 二进制、着色器或预设，不切换独立 Loader。
当前为 Calc 源码接入候选；ReShade 串联、原生部署与手动清理专项共 40 项及 2 个子用例通过，
真实游戏兼容性未验证，不标为稳定支持。沙箱内 DLL 原子替换受限的失败已在沙箱外同范围复核。
工具页已增加待实测的[神经渲染实验配置入口](../features/dlss-neural-rendering.md)，复用本文串联规则。
游戏内生效与 Calc 共存仍需[专项实机验收](dlss-neural-rendering.md)，不因界面入口存在而标为稳定支持。

## 代理入口与加载顺序

针对游戏目录已有 ReShade `d3d12.dll` 的布局，使用其公开的 `PROXY.EnableProxyLibrary` 与
`PROXY.ProxyLibrary` 配置串联本方宿主：

```text
HTGame.exe → ReShade 的 d3d12.dll → 本方 nte-calc-host.dll → 系统 d3d12.dll
```

ReShade 保持原文件名，计算器随附宿主保持清单原始字节，只改变游戏目录中的部署文件名。
现有本方宿主按自身地址确定模块及资源目录；插件导入绑定实际驻留宿主，避免误绑定 ReShade。
这里复用现有原生实现，没有给本方签名插件加载器增加任意第三方 DLL 接口。

上游接口证据为 ReShade 的
[配置读取与代理注册](https://github.com/crosire/reshade/blob/main/source/dll_main.cpp)、
[首次导出调用时加载串联模块](https://github.com/crosire/reshade/blob/main/source/hook_manager.cpp)和
[UTF-8 配置实现](https://github.com/crosire/reshade/blob/main/source/ini_file.cpp)。
上游 main 可变化；发布验收须冻结实际 ReShade 版本及 SHA-256，源码阅读不能替代运行验证。

## 接入与失败边界

- 首次接入通过环境设置的显式部署确认；自动管理只维护已经配置的串联，不修改首次发现的 ReShade 配置。
- 只读 PE 导出识别入口，不加载待识别 DLL；导出身份用于避免误覆盖，不作为安全签名或运行就绪证明。
- 当前仅接入本地 UTF-8 `ReShade.ini` 与本方插件宿主布局。外部 `BasePath`、环境目录覆盖、已有其他
  `PROXY` 配置、重复配置、目录/链接占位及未知串联目标均停止，不改玩家文件。
- 冻结入口哈希和配置原文。组件完整部署后，原子新增串联配置；保留无关配置、BOM 和换行。
  写入前复核账号/模式操作守卫、游戏状态与文件身份，配置变化即停止。
- 串联部署中途失败且已有写入时保留实际组件记录并进入待清理，不删除可能仍被 ReShade 引用的宿主。
  清理所有权及解除引用顺序以[组件清理契约](../reference/game-component-bundle.md#清理与待处理)为准。
- 文件哈希匹配和串联配置有效仅表示磁盘准备完成，不证明模块已加载、原生业务可用或画面正常。

ReShade 使用 `dxgi.dll` 的已有安装不需要这条 D3D12 同名串联映射，计算器保持原部署布局；
该组合的图形共存仍需单独验收。既有第三方代理链不自动拼接成多级链。

## 发布前验证

先执行 PE 识别、首次显式接入、自动更新、配置变更拒绝、部分写入待清理、旧记录误归属与解除串联
的专项用例，再做真实 Windows 游戏验收：记录游戏、驱动、ReShade 和本方整包身份，分别核对
原生同步、战报、HUD、ReShade 效果、游戏重启与退出清理；检查玩家更换预设和更新 ReShade 后的行为。
中文游戏路径需验证插件导入绑定所需的 Windows 短路径可用性；现有宿主不能生成无损导入路径时须报错。
DLSS/Streamline 组合单列实测，不因基础串联成功而宣称全部兼容。
