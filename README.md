# 门店价签发布工作台

本地门店价签发布系统，支持 CSV 导入、逐行校验、审批流转、发布打印、版本回滚等完整业务流程。

## 技术栈

- **后端**: Python Flask + SQLAlchemy + SQLite
- **前端**: React 18 + Ant Design 5 + Vite
- **持久化**: SQLite 本地数据库（文件：`backend/instance/pricelabel.db`）

## 目录结构

```
zgw-00145/
├── backend/                    # 后端项目
│   ├── app.py                  # Flask 主应用（所有接口）
│   ├── models.py               # 数据模型定义
│   ├── requirements.txt        # Python 依赖
│   └── instance/               # SQLite 数据库目录（自动生成）
│       └── pricelabel.db
├── frontend/                   # 前端项目
│   ├── src/
│   │   ├── pages/              # 所有页面组件
│   │   ├── App.jsx
│   │   ├── main.jsx
│   │   ├── index.css
│   │   └── utils/api.js        # Axios 封装
│   ├── index.html
│   ├── vite.config.js
│   └── package.json
├── start-backend.ps1           # 后端启动脚本
├── start-frontend.ps1          # 前端启动脚本
├── start-all.ps1               # 一键启动（前后端）
└── README.md
```

## 快速启动

### 方式一：一键启动（推荐）

```powershell
# 在项目根目录执行
.\start-all.ps1
```

### 方式二：分别启动

#### 1. 启动后端服务（端口 5000）

```powershell
# 终端1 - 后端
cd backend
pip install -r requirements.txt
python app.py
```

#### 2. 启动前端服务（端口 5173）

```powershell
# 终端2 - 前端
cd frontend
npm install
npm run dev
```

启动完成后，浏览器访问：**http://localhost:5173**

## 测试账号

| 角色 | 用户名 | 密码 | 权限 |
|------|--------|------|------|
| 管理员 | `admin` | `admin123` | 全部权限（含审批、配置、回滚） |
| 运营 | `operator` | `operator123` | 导入、提交、查看 |
| 店员 | `clerk` | `clerk123` | 查看、打印 |

## 核心功能验收清单

### ✅ 1. 价签导入（运营/管理员）

1. 登录运营账号 `operator`
2. 进入 **导入批次** 页面
3. 点击 **下载模板** 获取 CSV 模板
4. 填写数据后点击 **上传价签 CSV**
5. 系统显示：
   - 批次号、文件名
   - 校验通过/失败行数
   - **逐行校验结果**（含错误原因）
6. 点击 **查看校验详情** 可翻页浏览所有行校验记录

**模板 CSV 格式**：
```csv
SKU,门店,原价,促销价,生效开始时间,生效结束时间,模板
SKU001,北京朝阳店,99.00,69.00,2026-07-01 00:00:00,2026-07-31 23:59:59,default
SKU002,上海浦东店,199.00,149.00,2026-06-25 00:00:00,2026-07-15 23:59:59,promotion
```

### ✅ 2. 异常校验场景

| 校验项 | 触发条件 | 结果 |
|--------|----------|------|
| 促销价高于原价 | 促销价 > 原价 | ❌ 校验失败，提示 |
| 折扣低于下限 | 促销价/原价 < 折扣下限（默认50%） | ❌ 校验失败 |
| 门店不在白名单 | 门店名未在配置白名单内 | ❌ 校验失败 |
| 生效时段重叠 | 同门店同SKU发布窗口有重叠 | ❌ 校验失败 |
| 空SKU/门店/价格 | 必填字段为空 | ❌ 校验失败 |
| 时间格式错误 | 生效时间无法解析 | ❌ 校验失败 |

### ✅ 3. 审批流程（管理员）

1. 运营提交：**价签管理** → 选择草稿 → 批量提交
2. 管理员登录 `admin` → **价签审批**
3. 可批量 **通过** 或 **驳回**（需填原因）
4. 通过后自动：
   - 状态变更为 **已发布**
   - 加入 **待打印清单**
   - 写入审批人与时间

**权限校验**：店员/运营无法审批，页面会提示无权限。

### ✅ 4. 发布与打印

- **发布窗口**：可在系统配置设置允许发布的时间段（默认工作日9:00-18:00）
- **打印清单**：审批通过后自动生成
- **标记已打印**：店员可在打印清单勾选后标记

### ✅ 5. 版本回滚（管理员）

1. 进入已发布价签的 **详情页**
2. 点击 **回滚此价签** 按钮
3. 可选两种方式：
   - **直接标记回滚**：状态变为"已回滚"，不生成新版本
   - **回滚到历史版本**：选择历史版本，生成新版本号，写入历史
4. 回滚原因必填，操作记入 **回滚历史** 页面

**禁止场景**：
- 非已发布状态不可回滚
- 指定不存在的版本号会报错
- 回滚后与其他时段冲突会被拦截

### ✅ 6. 导出功能

- **价签管理** → 导出 CSV（含筛选条件）
- **打印清单** → 导出 CSV

### ✅ 7. 系统配置（管理员）

- **折扣下限**：最低允许折扣比例（如 0.5 = 5折）
- **门店白名单**：可导入的门店列表
- **模板字段**：价签模板字段定义（JSON）
- **发布窗口**：允许发布的时间范围

### ✅ 8. 重启一致性

SQLite 文件存储在 `backend/instance/pricelabel.db`，重启服务后：
- 所有价签数据（草稿/待审/已发布/已回滚）一致
- 回滚历史记录完整
- 系统配置保持
- 筛选导出功能正常

### ✅ 9. 交接单演练中心

> 让第一次接手的人不看源码也能在系统里完整跑通全流程。

**核心功能：**
- 🎯 **分角色入口**：管理员、运营、店员三种角色切换演练
- 📦 **可重复导入的演示数据**：一键导入演示数据，支持重置后重新导入
- 📚 **接口说明页**：所有核心接口的方法、路径、参数、权限、请求/响应示例
- 📋 **操作清单**：照着就能复现的步骤清单，包含正常流程和异常分支
- ⏱️ **演练时间线**：每次演练生成完整的操作时间线
- 📊 **验收记录导出**：自动生成验收记录，支持 CSV 导出
- 🔔 **页面操作提示**：每一步都有操作指引和预期结果
- 💾 **演练记录落库**：服务重启后仍可回看历史演练

**四种拦截验证（必过）：**

| 拦截场景 | 说明 | 错误码 |
|----------|------|--------|
| 同一批数据重复导入 | 相同 batch_id 重复导入会被拦截 | `DUPLICATE_DATA` |
| 旧单作废后继续拿来演练 | 作废的交接单不能再签收/操作 | `VOIDED_SHEET` |
| 不同角色越权查看或代签 | 非创建者不能操作他人的演练 | `PERMISSION_DENIED` / 403 |
| 日志和导出内容对不上 | 导出数据与操作日志交叉校验 | `CONSISTENCY_CHECK_FAILED` |

**最短复现步骤（5步）：**
1. 登录管理员账号（`admin` / `admin123`）
2. 进入 **演练中心** → 选择"交接单完整流程演练" → 点击"开始演练"
3. 依次执行前7步：导入数据 → 提交 → 审批 → 创建交接单 → 检查冲突 → 签收 → 作废
4. 执行异常分支验证：重复导入拦截、作废单拦截、越权验证
5. 查看日志和导出验收记录，确认所有操作留痕

**运行自动化测试：**
```powershell
cd backend
python test_drill.py
```

## 接口速览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/login` | 登录 |
| POST | `/api/auth/logout` | 登出 |
| GET | `/api/config` | 获取配置 |
| PUT | `/api/config` | 更新配置（admin） |
| POST | `/api/import` | 上传 CSV 导入 |
| GET | `/api/import/batches` | 批次列表 |
| GET | `/api/import/batches/:id` | 批次校验详情 |
| GET | `/api/labels` | 价签列表（支持筛选/分页） |
| GET | `/api/labels/:id` | 价签详情（含历史/版本） |
| POST | `/api/labels/submit` | 批量提交审批 |
| POST | `/api/labels/approve` | 批量审批通过/驳回（admin） |
| POST | `/api/labels/:id/rollback` | 回滚价签（admin） |
| GET | `/api/print-queue` | 打印清单 |
| POST | `/api/print-queue/mark-printed` | 标记已打印 |
| GET | `/api/rollback-history` | 回滚历史 |
| GET | `/api/export/labels` | 导出价签 CSV |
| GET | `/api/export/print-queue` | 导出打印 CSV |
| GET | `/api/handover-sheets` | 交接单列表（支持筛选/分页） |
| POST | `/api/handover-sheets` | 创建交接单（admin, operator） |
| GET | `/api/handover-sheets/:id` | 交接单详情（含明细、日志） |
| POST | `/api/handover-sheets/:id/sign` | 签收交接单 |
| POST | `/api/handover-sheets/:id/void` | 作废交接单（admin） |
| POST | `/api/handover-sheets/:id/check-conflicts` | 检查冲突 |
| GET | `/api/handover-sheets/available-labels` | 获取可加入交接单的价签 |
| GET | `/api/handover-logs` | 交接单操作日志 |
| GET | `/api/export/handover-sheets` | 导出交接单列表 CSV |
| GET | `/api/export/handover-sheet/:id` | 导出交接单明细 CSV |
| GET | `/api/export/handover-logs` | 导出交接单日志 CSV |
| GET | `/api/stats/overview` | 工作台统计 |
| **GET** | **`/api/drill/scenarios`** | **演练场景列表** |
| **POST** | **`/api/drill/start`** | **开始一次演练** |
| **GET** | **`/api/drill/sessions`** | **演练历史列表** |
| **GET** | **`/api/drill/sessions/:id`** | **演练详情（含步骤）** |
| **POST** | **`/api/drill/sessions/:id/steps/:key/execute`** | **执行演练步骤** |
| **GET** | **`/api/drill/sessions/:id/timeline`** | **演练时间线** |
| **POST** | **`/api/drill/sessions/:id/restart`** | **重置演练** |
| **POST** | **`/api/drill/demo-data/import`** | **导入演示数据** |
| **GET** | **`/api/drill/demo-data`** | **演示数据列表** |
| **POST** | **`/api/drill/demo-data/:key/reset`** | **重置演示数据** |
| **GET** | **`/api/drill/api-docs`** | **接口说明文档** |
| **GET** | **`/api/drill/checklist`** | **操作清单** |
| **GET** | **`/api/drill/export/acceptance/:id`** | **导出验收记录 CSV** |
| **GET** | **`/api/drill/export/checklist/:scenario`** | **导出操作清单 CSV** |

## 常见问题

**Q：npm install 慢？**
```bash
npm config set registry https://registry.npmmirror.com
```

**Q：pip install 慢？**
```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**Q：想重置所有数据？**
```powershell
# 删除数据库文件，重启后端会自动重建
Remove-Item backend/instance/pricelabel.db
```

**Q：前端 API 走什么地址？**
Vite 代理 `/api/*` → `http://localhost:5000`，无需跨域配置。
