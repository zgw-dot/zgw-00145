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
| GET | `/api/stats/overview` | 工作台统计 |

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
