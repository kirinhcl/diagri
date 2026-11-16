// Fixture strings a page may still show for now. Each entry is
// { page, fixture, path, batch: 2 | 3 | "keep", why }: `path` is "a.b" or "a[*].b" inside the fixture,
// `batch` is the batch that stops showing it, or "keep" for names the operator chose themselves.
export const EXEMPTIONS = [
  { page: "stage", fixture: "run-sheet.json", path: "findings[*].message", batch: 2, why: "服务器整句（C4，STG-01）" },
  { page: "stage", fixture: "run-sheet-pending.json", path: "findings[*].message", batch: 2, why: "服务器整句（C4，STG-01）" },
  { page: "stage", fixture: "measurements.json", path: "measurements[*].metric", batch: "keep", why: "测量指标名由录入人自己填写（TSK-06），照原样显示，也照原样出现在表单的候选和“正在更正”提示里" },
];
