# Obsidian Vault 通用同步 SKILL

## 适用场景

- 任何本地项目需要把对话、文档、会议纪要沉淀到 Obsidian；
- 支持“一次执行”和“定时执行”；
- 支持多 vault、多项目独立配置。

## 目录结构

```
tools/obsidian_exporter/
├── config.example.yaml
├── exporter.py
├── import_conversations.py
├── sync_docs.py
├── cli.py
└── SKILL.md
```

## 快速开始

```bash
python3 tools/obsidian_exporter/cli.py init
python3 tools/obsidian_exporter/cli.py export
python3 tools/obsidian_exporter/cli.py sync-docs
```

## 定时任务

```bash
# macOS / Linux
*/4 * * * * cd /Users/lv111101/Documents/hermass-observer-product && python3 tools/obsidian_exporter/cli.py export
```

## 配置说明

- `vault`: Obsidian vault 根目录
- `source_db`: 对话数据库路径
- `daily_subdir`: 按日导出目录
- `archive_subdir`: 归档目录
- `markdown_glob`:结果的文档同步范围

## 通用规则

- 所有导出都生成 Markdown；
- 支持按日期增量；
- Vault 内文件可直接用于搜索、图谱、MOC 索引。
