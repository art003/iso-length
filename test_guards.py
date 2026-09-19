from __future__ import annotations

import unittest
from pathlib import Path

from extract import extract_pdf
from guards import apply_guards

ROOT = Path(__file__).resolve().parent
PDF = ROOT / "data" / "02_Изометрии_10_листов.pdf"


def _decisions(sheet, mapping: dict[str, str]) -> dict:
    items = [{"id": c.cid, "decision": mapping.get(c.cid, "include"), "role": "main", "reason": mapping.get(c.cid + "_r", "")} for c in sheet.candidates]
    return {"line_id": sheet.line_id, "items": items, "notes": []}


def _sum_include(sheet, llm) -> int:
    by = {c.cid: c.value_mm for c in sheet.candidates}
    return sum(by[it["id"]] for it in llm["items"] if it["decision"] == "include" and it["id"] in by)


class GuardRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not PDF.exists():
            raise unittest.SkipTest("нет учебного pdf")
        cls.by_no = {s.sheet_no: s for s in extract_pdf(PDF, {1, 2, 4, 6, 7, 10})}

    def test_sheet1_z_plus_is_length(self):
        s = self.by_no[1]
        d1 = next(c for c in s.candidates if c.value_mm == 1383)
        self.assertIn("near_plant_coord", d1.flags)
        llm = _decisions(s, {"D1": "not_length", "D1_r": "вертикальная координата Z+"})
        out, notes = apply_guards(s.candidates, llm)
        by = {it["id"]: it["decision"] for it in out["items"]}
        self.assertEqual(by[d1.cid], "include")
        self.assertTrue(any("не координата" in n for n in notes))

    def test_sheet6_two_runs_and_overlap_overall(self):
        s = self.by_no[6]
        d6 = next(c for c in s.candidates if c.value_mm == 2950)
        d8 = next(c for c in s.candidates if c.value_mm == 2400)
        d11 = next(c for c in s.candidates if c.value_mm == 3505)
        self.assertIn("overall_pair", d6.flags)
        self.assertNotIn("overall_pair", d8.flags)
        mapping = {c.cid: "include" for c in s.candidates}
        mapping[d6.cid] = "include"
        mapping[d8.cid] = "exclude_nested"
        mapping[d8.cid + "_r"] = "габарит поверх D7"
        mapping[d11.cid] = "exclude_nested"
        mapping[d11.cid + "_r"] = "габарит поверх D10"
        out, notes = apply_guards(s.candidates, _decisions(s, mapping))
        by = {it["id"]: it["decision"] for it in out["items"]}
        self.assertEqual(by[d6.cid], "exclude_nested")
        self.assertEqual(by[d8.cid], "include")
        self.assertEqual(by[d11.cid], "exclude_nested")
        self.assertTrue(any("два прогона" in n for n in notes))

    def test_sheet7_nested_stays_out(self):
        s = self.by_no[7]
        nested = {c.cid: "exclude_nested" for c in s.candidates if c.value_mm in (916, 300)}
        nested.update({c.cid + "_r": f"внутри {1950 if c.value_mm == 916 else 840}" for c in s.candidates if c.value_mm in (916, 300)})
        mapping = {c.cid: "include" for c in s.candidates}
        mapping.update(nested)
        out, _ = apply_guards(s.candidates, _decisions(s, mapping))
        by = {it["id"]: it for it in out["items"]}
        for c in s.candidates:
            if c.value_mm in (916, 300):
                self.assertEqual(by[c.cid]["decision"], "exclude_nested")
        length = _sum_include(s, out)
        self.assertEqual(length, 4306)

    def test_sheet10_lt_overall(self):
        s = self.by_no[10]
        d5 = next(c for c in s.candidates if c.value_mm == 4116)
        mapping = {c.cid: "include" for c in s.candidates}
        out, notes = apply_guards(s.candidates, _decisions(s, mapping))
        by = {it["id"]: it["decision"] for it in out["items"]}
        self.assertEqual(by[d5.cid], "exclude_nested")
        self.assertTrue(any("LT" in n for n in notes))
        for c in s.candidates:
            if c.value_mm == 244:
                self.assertEqual(by[c.cid], "not_length")
        self.assertNotIn("ambiguous", by.values())

    def test_sheet2_stacked_overall(self):
        s = self.by_no[2]
        d9 = next(c for c in s.candidates if c.value_mm == 10200)
        self.assertIn("overall_pair", d9.flags)
        d8 = next(c for c in s.candidates if c.value_mm == 4072)
        self.assertNotIn("overall_pair", d8.flags)

    def test_locked_untouched(self):
        s = self.by_no[1]
        llm = _decisions(s, {"D1": "not_length", "D1_r": "координата Z+"})
        llm["locked"] = True
        out, notes = apply_guards(s.candidates, llm)
        self.assertEqual(notes, [])
        by = {it["id"]: it["decision"] for it in out["items"]}
        self.assertEqual(by[next(c.cid for c in s.candidates if c.value_mm == 1383)], "not_length")


if __name__ == "__main__":
    unittest.main()
