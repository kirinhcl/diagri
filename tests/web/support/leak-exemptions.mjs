// Fixture strings a page may still show for now. Each entry is
// { page, fixture, path, shown?, batch: 2 | 3 | "keep", why }: `path` is "a.b", "a[*].b" or "a[k=v].b"
// inside the fixture, `shown` says how the page shows the value when not as it is ("richText" or
// "folded", see leaks.mjs), `batch` is the batch that stops showing it, or "keep" for names the
// operator chose themselves.
export const EXEMPTIONS = [
  { page: "stage", fixture: "measurements.json", path: "measurements[*].metric", batch: "keep", why: "测量指标名由录入人自己填写（TSK-06），照原样显示，也照原样出现在表单的候选和“正在更正”提示里" },
  { page: "round", fixture: "report.json", path: "report.model_limitations[*]", batch: 3, why: "模型写的文字（C5）" },
  { page: "round", fixture: "report.json", path: "report.unresolved[*]", batch: 3, why: "模型写的文字（C5）" },
  { page: "round", fixture: "report.json", path: "report.next_round", batch: 3, why: "模型写的文字（C5）" },
  { page: "round", fixture: "report.json", path: "primary_endpoint", batch: "keep", why: "主要指标名由设计协议的人自己填写（RND-11），在带引号的名字里照原样显示，审阅时要靠它对上测量" },
  { page: "project", fixture: "conversation.json", path: "entries[kind=reply].text", shown: "richText", batch: 3, why: "模型写的回复（C5，P-10）" },
  { page: "project", fixture: "holdouts.json", path: "holdouts[*].outcome_fields[*]", batch: "keep", why: "结局字段名由操作员登记留出批次时自己填写（P-07），照原样显示" },
  { page: "project", fixture: "project.json", path: "tasks[*].question", shown: "folded", batch: 3, why: "委派和后续任务的问题是模型写的（C5，P-06）；操作员自己的目标在同一列，本身不含代码" },
  { page: "inbox", fixture: "inbox.json", path: "items[*].detail.question", shown: "folded", batch: 3, why: "研究任务的问题是模型写的（C5，INB-01）" },
  { page: "alerts", fixture: "alerts.json", path: "alerts[kind=audit_finding].params.summary", batch: 3, why: "模型写的监察备注（C5，ALT-11）" },
  { page: "alerts", fixture: "alerts.json", path: "alerts[kind=audit_finding].params.evidence[*]", batch: 3, why: "模型写的监察备注（C5，ALT-11）" },
];
