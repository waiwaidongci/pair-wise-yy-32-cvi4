import sqlite3, sys, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import ApiError, BatchService, Store


def stamp(days: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat().replace("+00:00", "Z")


class BatchFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.s = BatchService(Store(Path(self.tmp.name) / "b.db"))
        self.f1 = self.s.register_factory("qa", "qa", "F1", "一厂", "CN")["id"]
        self.f2 = self.s.register_factory("qa", "qa", "F2", "二厂", "CN")["id"]
        self.future = stamp(3)

    def tearDown(self): self.s.store.close(); self.tmp.cleanup()

    def revision(self, batch_id: int) -> int:
        return self.s.batch_detail(batch_id)["batch"]["revision"]

    def test_full_investigation_retest_rework_and_release(self):
        batch = self.s.create_batch("operator", "operator", self.f1, "B-1", "药片", "2026-01-01", "2028-01-01")
        dev = self.s.add_deviation("operator", "operator", self.f1, batch["id"], "minor", "装量轻微偏离", self.future, batch["revision"])
        failed = self.s.record_test("lab", "lab", self.f1, batch["id"], "含量", 89, 95, 105, self.revision(batch["id"]))
        self.assertFalse(failed["passed"])
        passed = self.s.record_test("lab", "lab", self.f1, batch["id"], "含量", 99, 95, 105, self.revision(batch["id"]))
        self.assertTrue(passed["passed"])
        closed = self.s.close_deviation("qa", "qa", dev["id"], "调整灌装参数", "灌装记录与参数复核单", self.revision(batch["id"]))
        self.assertEqual("qa", closed["closed_by"])
        self.assertEqual("灌装记录与参数复核单", closed["evidence_summary"])
        rw = self.s.plan_rework("operator", "operator", self.f1, batch["id"], "返工包装", self.revision(batch["id"]))
        self.s.complete_rework("operator", "operator", self.f1, rw["id"], self.revision(batch["id"]))
        self.s.record_stability("lab", "lab", self.f1, batch["id"], "25C/60RH", "3m", 99, 105, self.revision(batch["id"]))
        result = self.s.decide("qa", "qa", batch["id"], "release", "调查关闭，复测合格", self.revision(batch["id"]))
        self.assertEqual("released", result["batch"]["state"])
        self.assertEqual(1, len(self.s.batch_detail(batch["id"])["decisions"]))

    def test_critical_block_conditional_exception_and_factory_conflict(self):
        batch = self.s.create_batch("operator", "operator", self.f1, "B-2", "胶囊", "2026-02-01", "2028-02-01")
        self.s.record_test("lab", "lab", self.f1, batch["id"], "含量", 100, 95, 105, batch["revision"])
        crit = self.s.add_deviation("inspector", "inspector", self.f1, batch["id"], "critical", "无菌数据异常", self.future, self.revision(batch["id"]))
        current = self.revision(batch["id"])
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
        overdue = self.s.add_deviation("operator", "operator", self.f1, batch["id"], "minor", "环境监测延迟", stamp(-1), self.revision(batch["id"]))
        current = self.revision(batch["id"])
        with self.assertRaises(ApiError) as blocked:
            self.s.decide("qa", "qa", batch["id"], "release", "尝试放行", current)
        self.assertEqual(409, blocked.exception.status)
        self.assertIn(str(overdue["id"]), blocked.exception.message)
        self.assertEqual([overdue["id"]], blocked.exception.details["overdue_deviations"])
        self.s.approve_exception("qa", "qa", overdue["id"], "暂时接受", self.future, current)
        with self.assertRaises(ApiError) as conditional_blocked:
            self.s.decide("qa", "qa", batch["id"], "conditional", "尝试有条件放行", self.revision(batch["id"]), "EX-1")
        self.assertEqual([overdue["id"]], conditional_blocked.exception.details["overdue_deviations"])
        self.s.close_deviation("qa", "qa", overdue["id"], "补充监测", "监测报告与趋势分析", self.revision(batch["id"]))
        result = self.s.decide("qa", "qa", batch["id"], "release", "超期偏差已关闭", self.revision(batch["id"]))
        self.assertEqual("released", result["batch"]["state"])

    def test_extension_only_before_due_and_keeps_original_date(self):
        batch = self.s.create_batch("operator", "operator", self.f1, "B-4", "药片", "2026-01-01", "2028-01-01")
        dev = self.s.add_deviation("operator", "operator", self.f1, batch["id"], "minor", "待调查", self.future, batch["revision"])
        current = self.revision(batch["id"])
        later, much_later = stamp(10), stamp(20)
        with self.assertRaises(ApiError):
            self.s.extend_deviation("qa", "qa", dev["id"], "", later, current)
        with self.assertRaises(ApiError):
            self.s.extend_deviation("qa", "qa", dev["id"], "需要更多时间", stamp(1), current)
        extended = self.s.extend_deviation("qa", "qa", dev["id"], "等待供应商报告", later, current)
        self.assertEqual(self.future, extended["original_due_at"])
        self.assertEqual(later, extended["due_at"])
        self.assertEqual("等待供应商报告", extended["extension_reason"])
        self.assertEqual("qa", extended["extended_by"])
        again = self.s.extend_deviation("qa", "qa", dev["id"], "报告仍未到", much_later, self.revision(batch["id"]))
        self.assertEqual(self.future, again["original_due_at"])
        self.assertEqual(much_later, again["due_at"])

    def test_overdue_deviation_cannot_be_extended(self):
        batch = self.s.create_batch("operator", "operator", self.f1, "B-5", "药片", "2026-01-01", "2028-01-01")
        dev = self.s.add_deviation("operator", "operator", self.f1, batch["id"], "minor", "已经超期", stamp(-1), batch["revision"])
        with self.assertRaises(ApiError) as blocked:
            self.s.extend_deviation("qa", "qa", dev["id"], "想改到未来", self.future, self.revision(batch["id"]))
        self.assertEqual(409, blocked.exception.status)
        self.assertIn("超期", blocked.exception.message)

    def test_close_requires_evidence_summary(self):
        batch = self.s.create_batch("operator", "operator", self.f1, "B-6", "药片", "2026-01-01", "2028-01-01")
        dev = self.s.add_deviation("operator", "operator", self.f1, batch["id"], "minor", "待关闭", self.future, batch["revision"])
        with self.assertRaises(ApiError) as missing:
            self.s.close_deviation("qa", "qa", dev["id"], "纠正措施", "", self.revision(batch["id"]))
        self.assertEqual(400, missing.exception.status)
        closed = self.s.close_deviation("qa", "qa", dev["id"], "纠正措施", "证据摘要", self.revision(batch["id"]))
        self.assertEqual("closed", closed["status"])
        self.assertEqual("证据摘要", closed["evidence_summary"])
        self.assertEqual("qa", closed["closed_by"])


class OldDatabaseMigrationTest(unittest.TestCase):
    def test_old_database_upgraded_and_records_survive(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "old.db"
        conn = sqlite3.connect(path)
        conn.executescript("""
        CREATE TABLE factories (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, country TEXT NOT NULL);
        CREATE TABLE batches (
          id INTEGER PRIMARY KEY AUTOINCREMENT, factory_id INTEGER NOT NULL REFERENCES factories(id),
          batch_no TEXT NOT NULL, product TEXT NOT NULL, mfg_date TEXT NOT NULL, expiry_date TEXT NOT NULL,
          state TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, created_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          UNIQUE(factory_id,batch_no)
        );
        CREATE TABLE deviations (
          id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id INTEGER NOT NULL REFERENCES batches(id),
          severity TEXT NOT NULL, title TEXT NOT NULL, due_at TEXT,
          status TEXT NOT NULL, corrective_action TEXT,
          exception_reason TEXT, exception_until TEXT, exception_approved_by TEXT,
          closed_by TEXT, closed_at TEXT, created_by TEXT NOT NULL, created_at TEXT NOT NULL
        );
        INSERT INTO factories(code,name,country) VALUES('F-OLD','旧工厂','CN');
        INSERT INTO batches(factory_id,batch_no,product,mfg_date,expiry_date,state,created_by,created_at,updated_at)
          VALUES(1,'B-OLD','旧批次','2025-01-01','2027-01-01','investigation','op','2025-01-02T00:00:00Z','2025-01-02T00:00:00Z');
        INSERT INTO deviations(batch_id,severity,title,due_at,status,created_by,created_at)
          VALUES(1,'minor','旧偏差','2026-01-01T00:00:00Z','open','op','2025-01-02T00:00:00Z');
        """)
        conn.commit(); conn.close()

        service = BatchService(Store(path)); self.addCleanup(service.store.close)
        detail = service.batch_detail(1)
        self.assertEqual("B-OLD", detail["batch"]["batch_no"])
        self.assertEqual("旧偏差", detail["deviations"][0]["title"])
        self.assertIsNone(detail["deviations"][0]["evidence_summary"])
        columns = {row[1] for row in service.store.conn.execute("PRAGMA table_info(deviations)")}
        self.assertTrue({"evidence_summary", "original_due_at", "extension_reason", "extended_by", "extended_at"} <= columns)
        closed = service.close_deviation("qa", "qa", 1, "旧库纠正", "旧库证据", detail["batch"]["revision"])
        self.assertEqual("closed", closed["status"])
        self.assertEqual("旧库证据", closed["evidence_summary"])


if __name__ == "__main__": unittest.main()
