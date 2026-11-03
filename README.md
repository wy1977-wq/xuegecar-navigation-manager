<div align="center">

# 🧭 XuegeCar NavigationManager

### ROS 2 智能小车导航任务管理模块

**XuegeCar 二次开发系列 · 第三期**

![ROS 2](https://img.shields.io/badge/ROS%202-Humble-22314E?style=flat-square&logo=ros)
![Python](https://img.shields.io/badge/Python-3.x-3776AB?style=flat-square&logo=python)
![Nav2](https://img.shields.io/badge/Nav2-NavigateToPose-007ACC?style=flat-square)
![Platform](https://img.shields.io/badge/Platform-XuegeCar-16A085?style=flat-square)

**Qt 目标位姿 · Nav2 Action · 任务状态 · 导航取消 · 运动权限**

</div>

---

## 📌 项目来源与声明

> 感谢 **出云科技** 提供的 ROS 2 智能小车硬件平台、基础开源工程和相关技术资料！
>
> 本仓库记录基于原有开源项目进行的导航任务管理功能二次开发与系统集成。ROS 2、AMCL、Nav2 及 NavFn 等第三方项目的算法不属于本仓库作者原创；其代码仍遵循各自许可证。

## 📖 1. 项目介绍

`NavigationManager` 作为 XuegeCar Qt 上位机和 Nav2 之间的**应用层导航任务管理模块**，用于将地图上指定的目标位姿与 Nav2 自主导航执行流程连接起来，并提供任务状态查询与取消入口。

本模块**不是 A* 或 DWB 算法的重新实现**。全局路径规划和路径跟随由 Nav2 的对应组件负责，`NavigationManager` 着重管理上层交互、执行权限和任务生命周期。

### 设计目标

- 🎯 接收 Qt 发布的地图目标位姿；
- 🧭 对接 Nav2 的 `NavigateToPose` Action；
- 🔒 利用 `enable_motion` 参数将通信验证与实际运动分开；
- 📊 提供导航状态查询入口；
- ⏹️ 提供取消导航任务的入口。

## ✨ 2. 核心功能

| 功能 | 对应接口/机制 | 用途 |
| :--- | :--- | :--- |
| 目标接收 | `/xuegecar/goal_pose` | 接收地图坐标系中的目标位姿 |
| 导航提交 | `/navigate_to_pose` | 将目标交给 Nav2 执行完整导航 |
| 运动权限 | `enable_motion` | 防止调试期间误提交运动任务 |
| 状态查询 | `/xuegecar/navigation_status` | 向 Qt 提供任务状态 |
| 导航取消 | `/xuegecar/cancel_navigation` | 请求结束当前导航任务 |

> 💡 `ComputePathToPose` 只计算路径；`NavigateToPose` 才会启动完整的导航执行流程。**规划成功不代表实车导航成功。**

## 🧩 3. 系统架构

```mermaid
flowchart TD
    UI["XuegeCar Qt 上位机"] -->|"目标位姿 PoseStamped"| Topic["/xuegecar/goal_pose"]
    Topic --> Manager["NavigationManager"]
    Manager --> Guard{"enable_motion 允许执行?"}
    Guard -->|否| Reject["仅验证通信 / 拒绝执行"]
    Guard -->|是| Action["/navigate_to_pose"]
    Action --> BT["Nav2 bt_navigator"]
    BT --> Plan["全局规划器 planner_server"]
    BT --> Control["局部控制器 controller_server"]
    Control --> Base["机器人底盘"]
    BT -->|"反馈及任务结果"| Manager
    UI -->|"查询 / 取消"| Manager
    Manager -->|"状态响应"| UI
