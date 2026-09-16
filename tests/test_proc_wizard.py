# -*- coding: utf-8 -*-
"""ตัวช่วยจัดซื้อจัดจ้าง - เดินครบทุกเส้นทาง ทุกปลายทางต้องมีผลลัพธ์และอ้างระเบียบ"""
from types import SimpleNamespace

import pytest

from app.routers.pages import PROC_CASES
from app.services.proc_wizard import NODES, RESULTS, walk, case_warnings


def _all_paths():
    """ไล่ทุกเส้นทางที่เป็นไปได้ (วงเงินใช้ค่าแทนของแต่ละช่วง)"""
    out = []

    def go(node_id, answers):
        node = NODES[node_id]
        if node["kind"] == "amount":
            prev = 0
            steps = []
            for r in node["ranges"]:
                sample = (r["max"] if r["max"] is not None else prev + 1)
                steps.append((sample, r))
                prev = r["max"] or prev
        else:
            steps = list(enumerate(node["options"]))
        for ans, step in steps:
            if "result" in step:
                out.append((answers + [ans], step["result"]))
            else:
                go(step["next"], answers + [ans])

    go("start", [])
    return out


PATHS = _all_paths()


def test_every_node_reachable_and_every_next_exists():
    reached = {"start"}
    for node in NODES.values():
        for step in node.get("options", []) + node.get("ranges", []):
            if "next" in step:
                assert step["next"] in NODES, f"ไม่มีโหนด {step['next']}"
                reached.add(step["next"])
            else:
                assert step["result"] in RESULTS, f"ไม่มีผลลัพธ์ {step['result']}"
    assert reached == set(NODES), f"โหนดที่ไปไม่ถึง: {set(NODES) - reached}"


@pytest.mark.parametrize("answers,result", PATHS)
def test_path_ends_with_referenced_result(answers, result):
    got = walk(answers)
    assert got.get("result") == result
    res = RESULTS[result]
    assert res["title"] and res["why"]
    # ทุกปลายทางที่เป็นรูปแบบเอกสาร ต้องอ้างระเบียบ และต้องมีอยู่จริงในระบบ
    if "case" in res:
        assert res["refs"], f"{result} ไม่ได้อ้างระเบียบ"
        assert res["case"] in PROC_CASES
    else:
        assert "go" in res or res.get("out_of_scope")


def test_key_decisions():
    buy, hire = [0, 0, 0], [0, 0, 1, 0]
    assert walk(buy + [8000, 0])["result"] == "w119t1"          # ซื้อ 8,000 ตาราง 1
    assert walk(buy + [8000, 1, 0])["result"] == "w804"         # ไม่อยู่ตาราง 1 แต่ร้านประกาศราคา
    assert walk(buy + [30000, 0])["result"] == "w804"
    assert walk(buy + [30000, 1])["result"] == "normal"
    assert walk(buy + [50000.01])["result"] == "normal"         # เกิน 50,000 ใช้ ว.804 ไม่ได้
    assert walk(buy + [500000])["result"] == "normal"
    assert walk(buy + [500000.01])["result"] == "over_limit"
    assert walk(hire + [30000])["result"] == "normal"           # ว.804 ไม่ใช้กับการจ้าง
    assert walk(hire + [8000, 0])["result"] == "w119t1"
    assert walk([0, 0, 1, 1])["result"] == "w877"
    assert walk([0, 1])["result"] == "clause79"
    assert walk([1])["result"] == "w119t2"
    assert walk(buy + [8000, 0])["set"]["proc_type"] == "ซื้อ"


def _proc(case, total, ptype="ซื้อ"):
    return SimpleNamespace(proc_case=case, total_amount=total, proc_type=ptype)


def test_case_warnings():
    assert case_warnings(_proc("w119t1", 9000)) == []
    assert len(case_warnings(_proc("w119t1", 12000))) == 1
    assert case_warnings(_proc("w804", 40000)) == []
    assert len(case_warnings(_proc("w804", 40000, "จ้าง"))) == 1
    assert len(case_warnings(_proc("w804", 60000))) == 1
    assert case_warnings(_proc("normal", 500000)) == []
    assert "อยู่ระหว่างการพัฒนา" in case_warnings(_proc("normal", 600000))[0]
    assert case_warnings(_proc("w119t2", 900000)) == []         # ตาราง 2 ไม่มีเพดาน
