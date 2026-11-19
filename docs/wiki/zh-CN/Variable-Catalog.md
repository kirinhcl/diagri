# 变量目录

[English](../en/Variable-Catalog.md)

这一页写给研究人员和开发者。它说明协议、测量、快照和留出集共同使用的变量名清单，以及如何修改它。

## 它是做什么的

每个被测量的量和每个处理因子都有一个标准 ID，例如 `air_temperature`。没有共享清单时，协议写 `temp`，测量写 `Temperature`，脚本又按 `air temp` 过滤，数据就无法合并。目录给每个变量一个标准 ID、一个种类（`sensor`、`manual` 或 `factor`）、物理量、单位、方法，以及在合适时的允许范围 `min` 和 `max`。

目录就是文件 [`vocab/catalog.toml`](../../../src/growbridge/vocab/catalog.toml)。运行时在启动时加载一次，并把这同一个实例交给工作流、运行单检查和留出集登记。目录损坏时，运行时不会启动。

## 只追加的规则

条目的定义字段永远不变：`id`、`kind`、`quantity`、`unit`、`method`、`min`、`max`。记在某个 ID 下的数据，含义必须永远不变。

- 要加变量，追加一个条目，并提高文件里的 `version`。
- 要改变某个变量的含义，就新增一个 ID，把旧条目标为 `deprecated = true`，并把它的 `replaced_by` 设为新 ID。
- 已弃用的 ID 只有在同一协议的更早版本声明过它时，才会在协议里被接受。

## 锁文件

[`vocab/catalog.lock.json`](../../../src/growbridge/vocab/catalog.lock.json) 让这条规则可以被检查：

- `versions` 把每个目录版本映射到发布时文件的 SHA-256。
- `entries` 把每个 ID 映射到它的定义字段的摘要。

追加之后，把新版本的摘要和新条目的摘要加进锁文件。失败的锁测试会打印出要加的确切行。定义字段被改动，或已发布版本的文件不同，同样会让这些测试失败。

## 别名只是设备键

只有 sensor 条目有别名，它们就是设备自己的传感器键：`temp`、`humi`、`vpd`、`co2`、`ppfd`、`tempSoil`。别名让桥接的读数能解析到标准 ID。协议或测量必须使用标准 ID；在那里写别名会被拒绝，提示里会给出标准 ID。

## 本体术语

训练数据集导出（[训练数据集导出](Training-Dataset-Export.md)）可以用本体术语描述每个变量和单位。它们是目录的可选字段，不属于变量的定义，所以加上它们不会改变条目在锁文件里的摘要。

- 条目的 `refs` 是 CURIE 列表，例如 `PECO:...`。每一项的前缀必须是已知的，否则目录无法加载。已知前缀有 `PECO`、`ENVO`、`AGRO`、`PATO`、`UO`、`NCBITaxon`，以及 Crop Ontology 的各作物本体 `CO_<数字>`（[`vocab/curie.py`](../../../src/growbridge/vocab/curie.py)）。导出会把各前缀的基址写进 `croissant.json` 的 `@context`。
- `[unit_refs]` 是目录文件里的一张表。键是某个条目用到的 UCUM 单位代码，值是它对应的 Units Ontology（`UO:`）术语。目录加载时会检查这两点（[`vocab/catalog.py`](../../../src/growbridge/vocab/catalog.py)）。没有确认过术语的单位就不写。

**没有任何程序猜术语。** `refs` 和 `[unit_refs]` 在研究者逐条确认之前一直是空的。流程：

1. 在 OLS 或 AgroPortal 上为每个条目查出候选，记下 CURIE、术语标签、本体名称，以及本体版本或查询日期。手工性状用 Crop Ontology 的 variable、trait、method 和 scale；处理因子用 PECO；环境量用 ENVO 或 AGRO。
2. 研究者逐条确认；只有研究者能判断一个术语的定义和这个变量的测法是否一致。不确定的条目留空。
3. 把确认过的术语写进 `catalog.toml`，提高 `version`，并把新版本的摘要加进锁文件的 `versions`。

在此之前，导出照常列出这个变量，`mapped=false`，计入 `unmapped_variables`，`unit_uo` 列也保持为空。

目录第 2 版（2026-11-19）带上了第一批确认过的术语：`air_temperature`、`air_relative_humidity`、`co2_concentration`、`photosynthetic_photon_flux_density`、`soil_temperature` 和 `light` 有 `refs`，`Cel`、`%`、`[ppm]` 和 `umol/m2/s` 有 UO 术语。`vapour_pressure_deficit`、`canopy_area_growth`、`kPa` 和 `cm2/d` 没有，因为已知前缀里没有合适的术语。`light` 的术语 `PECO:0007224` light intensity exposure 只说明处理的类型：它的层级是灯具最大输出的百分比，不能和其他来源的光照层级相比。候选术语、出处和每条的取舍理由见 [`docs/superpowers/notes/2026-11-18-ontology-candidates.md`](../../superpowers/notes/2026-11-18-ontology-candidates.md)。

## 保存协议之前先声明变量

研究协议必须声明 `variables`，即目录 ID 的列表。出现以下情况时，保存会被 422 `param` 拒绝，并列出每一个问题：

- 列表为空，或同一个 ID 出现两次；
- 某个 ID 不在目录里、是别名，或已弃用且该协议更早的版本没有声明过；
- 主要终点不在已声明的变量里，或不是人工变量（它只从人工测量中分析）；
- 某个处理的因子键不是目录里的因子 ID。

所以，新实验用到的变量必须先进入目录，才能保存它的协议。缺少时，先把它加进目录（只追加、新版本、更新锁文件）。

## 它在下游管什么

- **测量。** 人工测量只能使用该实验的协议所声明的变量，单位必须是该变量的单位，数值必须在范围内。见[运行一轮研究](Run-a-Research-Round.md#记录一次测量)。
- **留出集。** 结局名称通过目录解析；目录无法解析的名称按留出的结局处理。见[科研方法](Research-Methodology.md#预测模型与留出数据)。
- **训练数据集。** 导出把目录的条目、术语和单位写进 `variables.csv`，把目录的 `version` 写进 `croissant.json`。
- **快照。** 每个数据快照包含 `catalog.json`，记录目录的 `version`、`digest`、数据用到的 `variables`，以及 `unresolved` 的名称。

## 另见

- [运行一轮研究](Run-a-Research-Round.md)
- [科研方法](Research-Methodology.md)
- [HTTP、工作台与 MCP 接口](API-Reference.md)
- [数据、档案与可追溯性](Data-Archive-and-Traceability.md)
