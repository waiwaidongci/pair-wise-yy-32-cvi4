import sqlite3, sys, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import ApiError, BatchService, Store


class BatchFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.s = BatchService(Store(Path(self.tmp.name) / "b.db"))
        self.f1 = self.s.register_factory("qa", "qa", "F1", "一厂", "CN")["id"]
        self.f2 = self.s.register_factory("qa", "qa", "F2", "二厂", "CN")["id"]
        self.future = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat().replace("+00:00", "Z")
        self.past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat().replace("+00:00", "Z")

    def tearDown(self): self.s.store.close(); self.tmp.cleanup()

    def _revision(self, batch_id):
        return self.s.batch_detail(batch_id)["batch"]["revision"]

    def test_full_investigation_retest_rework_and_release(self):
        batch = self.s.create_batch("operator", "operator", self.f1, "B-1", "药片", "2026-01-01", "2028-01-01")
        dev = self.s.add_deviation("operator", "operator", self.f1, batch["id"], "minor", "装量轻微偏离", self.future, batch["revision"])
        failed = self.s.record_test("lab", "lab", self.f1, batch["id"], "含量", 89, 95, 105, self._revision(batch["id"]))
        self.assertFalse(failed["passed"])
        passed = self.s.record_test("lab", "lab", self.f1, batch["id"], "含量", 99, 95, 105, self._revision(batch["id"]))
        self.assertTrue(passed["passed"])
        self.s.close_deviation("qa", "qa", dev["id"], "调整灌装参数", "灌装记录与复检数据已复核", self._revision(batch["id"]))
        rw = self.s.plan_rework("operator", "operator", self.f1, batch["id"], "返工包装", self._revision(batch["id"]))
        self.s.complete_rework("operator", "operator", self.f1, rw["id"], self._revision(batch["id"]))
        self.s.record_stability("lab", "lab", self.f1, batch["id"], "25C/60RH", "3m", 99, 105, self._revision(batch["id"]))
        result = self.s.decide("qa", "qa", batch["id"], "release", "调查关闭，复测合格", self._revision(batch["id"]))
        self.assertEqual("released", result["batch"]["state"])
        self.assertEqual(1, len(self.s.batch_detail(batch["id"])["decisions"]))

    def test_critical_block_conditional_exception_and_factory_conflict(self):
        batch = self.s.create_batch("operator", "operator", self.f1, "B-2", "胶囊", "2026-02-01", "2028-02-01")
        self.s.record_test("lab", "lab", self.f1, batch["id"], "含量", 100, 95, 105, batch["revision"])
        crit = self.s.add_deviation("inspector", "inspector", self.f1, batch["id"], "critical", "无菌数据异常", self.future, self._revision(batch["id"]))
        current = self._revision(batch["id"])
        with self.assertRaises(ApiError) as blocked:
            self.s.decide("qa", "qa", batch["id"], "release", "尝试放行", current)
        self.assertIn("关键偏差", blocked.exception.message)
        with self.assertRaises(ApiError):
            self.s.approve_exception("qa", "qa", crit["id"], "暂时接受", self.future, current)
        with self.assertRaises(ApiError):
            self.s.record_test("lab", "lab", self.f2, batch["id"], "水分", 1, 0, 2, current)
        with self.assertRaises(ApiError) as stale:
            self.s.record_test("lab", "lab", self.f1, batch["id"], "水分", 1, 0, 2, 1)
        self.assertEqual(409, stale.exception.status)

    def test_overdue_deviation_blocks_release_and_conditional_with_ids(self):
        batch = self.s.create_batch("operator", "operator", self.f1, "B-3", "药片", "2026-01-01", "2028-01-01")
        self.s.record_test("lab", "lab", self.f1, batch["id"], "含量", 100, 95, 105, batch["revision"])
        d1 = self.s.add_deviation("operator", "operator", self.f1, batch["id"], "minor", "已超期偏差一", self.past, self._revision(batch["id"]))
        d2 = self.s.add_deviation("operator", "operator", self.f1, batch["id"], "minor", "已超期偏差二", self.past, self._revision(batch["id"]))
        with self.assertRaises(ApiError) as blocked:
            self.s.decide("qa", "qa", batch["id"], "release", "尝试放行", self._revision(batch["id"]))
        self.assertEqual(409, blocked.exception.status)
        self.assertIn(str(d1["id"]), blocked.exception.message)
        self.assertIn(str(d2["id"]), blocked.exception.message)
        with self.assertRaises(ApiError) as blocked_cond:
            self.s.decide("qa", "qa", batch["id"], "conditional", "尝试有条件放行", self._revision(batch["id"]), "EX-1")
        self.assertIn(str(d1["id"]), blocked_cond.exception.message)
        with self.assertRaises(ApiError) as extend:
            self.s.approve_exception("qa", "qa", d1["id"], "事后补救延期", self.future, self._revision(batch["id"]))
        self.assertEqual(409, extend.exception.status)
        with self.assertRaises(ApiError) as no_evidence:
            self.s.close_deviation("qa", "qa", d1["id"], "纠正措施", "", self._revision(batch["id"]))
        self.assertEqual(400, no_evidence.exception.status)
        closed1 = self.s.close_deviation("qa", "qa", d1["id"], "纠正措施一", "调查证据摘要一", self._revision(batch["id"]))
        self.assertEqual("调查证据摘要一", closed1["evidence_summary"])
        self.assertEqual("qa", closed1["closed_by"])
        self.assertTrue(closed1["closed_at"])
        self.s.close_deviation("qa", "qa", d2["id"], "纠正措施二", "调查证据摘要二", self._revision(batch["id"]))
        result = self.s.decide("qa", "qa", batch["id"], "release", "超期偏差已关闭", self._revision(batch["id"]))
        self.assertEqual("released", result["batch"]["state"])

    def test_extension_before_due_date_keeps_original_and_allows_conditional(self):
        batch = self.s.create_batch("operator", "operator", self.f1, "B-4", "胶囊", "2026-01-01", "2028-01-01")
        self.s.record_test("lab", "lab", self.f1, batch["id"], "含量", 100, 95, 105, batch["revision"])
        dev = self.s.add_deviation("operator", "operator", self.f1, batch["id"], "minor", "待调查偏差", self.future, self._revision(batch["id"]))
        later = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat().replace("+00:00", "Z")
        extended = self.s.approve_exception("qa", "qa", dev["id"], "供应商报告待补", later, self._revision(batch["id"]))
        self.assertEqual(dev["due_at"], extended["due_at"])
        self.assertEqual(later, extended["exception_until"])
        self.assertEqual("供应商报告待补", extended["exception_reason"])
        result = self.s.decide("qa", "qa", batch["id"], "conditional", "例外有效期内", self._revision(batch["id"]), "EX-100")
        self.assertEqual("conditional", result["batch"]["state"])

    def test_old_database_migrated_and_records_usable(self):
        db = Path(self.tmp.name) / "old.db"
        conn = sqlite3.connect(db)
        conn.execute("""CREATE TABLE deviations (
          id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id INTEGER NOT NULL,
          severity TEXT NOT NULL, title TEXT NOT NULL, due_at TEXT,
          status TEXT NOT NULL, corrective_action TEXT,
          exception_reason TEXT, exception_until TEXT, exception_approved_by TEXT,
          closed_by TEXT, closed_at TEXT, created_by TEXT NOT NULL, created_at TEXT NOT NULL)""")
        conn.execute("INSERT INTO deviations(batch_id,severity,title,due_at,status,created_by,created_at) VALUES(1,'minor','旧库遗留偏差',NULL,'open','op','2026-01-01T00:00:00Z')")
        conn.commit(); conn.close()
        service = BatchService(Store(db))
        try:
            columns = {row["name"] for row in service.conn.execute("PRAGMA table_info(deviations)")}
            self.assertIn("evidence_summary", columns)
            legacy = service.conn.execute("SELECT * FROM deviations WHERE id=1").fetchone()
            self.assertEqual("旧库遗留偏差", legacy["title"])
            factory = service.register_factory("qa", "qa", "F-OLD", "旧工厂", "CN")
            batch = service.create_batch("operator", "operator", factory["id"], "B-OLD", "药片", "2026-01-01", "2028-01-01")
            self.assertEqual("manufactured", batch["state"])
        finally:
            service.store.close()


if __name__ == "__main__": unittest.main()
