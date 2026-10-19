"""Synthetic counterexamples complement the separately recorded COMSOL probes."""
import copy
import json
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot.diagnostic_modules import flow, flow_3d


def inventory():
    data = json.loads((ROOT / "data/fixtures/cases/baseline.json").read_text(encoding="utf-8-sig"))
    component = data["components"][0]
    g = component["geometries"][0]
    r, h = .025, 1
    g.update(dimension=3, axisymmetric=False, boundary_count=3, domain_count=1,
             feature_types=["Cylinder", "Finalize"], bounding_box=[-r,r,-r,r,0,h])
    ends = [{"boundary_id": i+1, "domain_ids": [1], "area": math.pi*r*r,
             "sample_coordinates": [[r*.5*math.cos(t),r*.5*math.sin(t),z] for t in range(9)],
             "sample_normals": [[0,0,1]]*9, "mean_curvatures": [0]*9, "gauss_curvatures": [0]*9}
            for i,z in enumerate((0,h))]
    wall = {"boundary_id": 3, "domain_ids": [1], "area": 2*math.pi*r*h,
            "sample_coordinates": [[r*math.cos(t),r*math.sin(t),.1+t*.1] for t in range(9)],
            "sample_normals": [[math.cos(t),math.sin(t),0] for t in range(9)],
            "mean_curvatures": [1/(2*r)]*9, "gauss_curvatures": [0]*9}
    g["three_dimensional_evidence"] = {"read_status":"read", "coordinate_names":["Xg","Yg","Zg"],
        "domains":[{"domain_id":1,"boundary_ids":[1,2,3],"volume":math.pi*r*r*h,"bounding_box":g["bounding_box"]}],
        "boundaries":ends+[wall]}
    for f in component["physics"][0]["features"]:
        f["selection_dimensions"] = [3 if f["type"] in {"FluidProperties", "init"} else 2]
        role = {"Inlet":[1],"Outlet":[2],"WallBC":[3],"Wall":[3]}.get(f["type"])
        if role:
            f["selected_entity_ids"] = role
            f["declared_entity_ids"] = [1,2,3] if f["type"] in {"WallBC","Wall"} else role
    return data


def run(data):
    return flow.run_instance(data,0,0,[])


def node(data, kind):
    return next(f for f in data["components"][0]["physics"][0]["features"] if f["type"] == kind)


class ThreeDimensionalFlowTests(unittest.TestCase):
    def test_normal_checked_new_contract_without_axis(self):
        result = run(inventory())
        self.assertEqual(result["status"], "checked")
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["model"]["profile"], "pipe-3d-v1")
        self.assertEqual(result["model"]["geometry"]["pipe_diameter_m"], .05)
        self.assertFalse(any("AXIS" in r["rule_id"] for r in result["rules"]))
        flow.validate(result["model"])

    def test_reversed_inlet_and_high_reynolds(self):
        for speed, code in ((-.1,"INLET_DIRECTION"),(2,"REYNOLDS_RISK")):
            with self.subTest(speed=speed):
                data=inventory()
                node(data,"Inlet")["evaluated_parameters"]["normal_velocity"]["value"]=speed
                self.assertIn(code, {f["code"] for f in run(data)["findings"]})

    def test_missing_outlet_and_empty_selection(self):
        data=inventory()
        node(data,"Outlet")["selected_entity_ids"]=[]
        codes={f["code"] for f in run(data)["findings"]}
        self.assertTrue({"MISSING_OUTLET","EMPTY_BOUNDARY_SELECTION"} <= codes)

    def test_ports_on_side_are_reported_and_re_skipped(self):
        data=inventory()
        node(data,"Inlet").update(selected_entity_ids=[3],declared_entity_ids=[3])
        result=run(data)
        self.assertIn("FLOW_FACE_SELECTION_INCONSISTENT",{f["code"] for f in result["findings"]})
        self.assertEqual(next(r for r in result["rules"] if r["rule_id"]=="REYNOLDS_RISK")["status"],"skipped")

    def test_missing_or_tampered_geometry_has_no_scale(self):
        for change in ("missing","volume","curvature","rotation"):
            with self.subTest(change=change):
                data=inventory()
                g=data["components"][0]["geometries"][0]
                if change=="missing": g.pop("three_dimensional_evidence")
                if change=="volume": g["three_dimensional_evidence"]["domains"][0]["volume"]*=2
                if change=="curvature": g["three_dimensional_evidence"]["boundaries"][2]["mean_curvatures"][0]=0
                if change=="rotation": g["feature_types"].append("Rotate")
                result=run(data)
                self.assertEqual(result["status"],"skipped")
                self.assertIsNone(result["model"]["geometry"]["pipe_diameter_m"])
                for code in ("MISSING_INLET","MISSING_OUTLET","REYNOLDS_RISK","FLOW_FACE_SELECTION_INCONSISTENT"):
                    self.assertEqual(next(r for r in result["rules"] if r["rule_id"]==code)["status"],"skipped")
                self.assertEqual(next(r for r in result["rules"] if r["rule_id"]=="INVALID_MATERIAL_PARAMETER")["status"],"checked")

    def test_solid_material_does_not_change_fluid_diameter(self):
        data=inventory()
        c=data["components"][0]
        g=c["geometries"][0]
        g.update(domain_count=2,bounding_box=[-.03,.03,-.03,.03,0,1],feature_types=["Cylinder","Cylinder","Union","Finalize"])
        solid=copy.deepcopy(c["materials"][0]); solid.update(tag="solid",domain_ids=[2])
        solid["density"]["value"]=-1
        c["materials"].append(solid)
        result=run(data)
        self.assertEqual(result["status"],"checked")
        self.assertEqual(result["findings"],[])
        self.assertEqual(result["model"]["geometry"]["pipe_diameter_m"],.05)

    def test_unknown_coupling_only_retains_material(self):
        result=flow.run_instance(inventory(),0,0,["/multiphysics/0"])
        self.assertEqual(result["status"],"skipped")
        self.assertEqual(next(r for r in result["rules"] if r["rule_id"]=="INVALID_MATERIAL_PARAMETER")["status"],"checked")

    def test_unverified_mode_and_slip_skip_numerics(self):
        for kind,key,value in (("Inlet","BoundaryCondition","MassFlow"),("WallBC","BoundaryCondition","Slip")):
            data=inventory();node(data,kind)["parameters"][key]=value
            result=run(data)
            self.assertEqual(next(r for r in result["rules"] if r["rule_id"]=="REYNOLDS_RISK")["status"],"skipped")

    def test_legacy_check_rejects_new_model(self):
        with self.assertRaisesRegex(flow.UnsupportedModel,"diagnose_inventory"):
            flow.check(flow.normalize(inventory()))

    def test_unbound_material_with_unresolved_port_has_executed_evaluation(self):
        data=inventory()
        node(data,"FluidProperties")["parameters"]["rho_mat"]="userdef"
        node(data,"Inlet")["evaluated_parameters"]["normal_velocity"].update(status="unresolved",value=None)
        result=run(data)
        self.assertIn("EVALUATION_UNAVAILABLE",{f["code"] for f in result["findings"]})
        self.assertEqual(next(r for r in result["rules"] if r["rule_id"]=="EVALUATION_UNAVAILABLE")["status"],"checked")

    def test_one_way_adjacency_does_not_prove_pipe(self):
        data=inventory()
        g=data["components"][0]["geometries"][0]
        g["three_dimensional_evidence"]["boundaries"].append({"boundary_id":4,"domain_ids":[1]})
        self.assertIsNone(run(data)["model"]["geometry"]["pipe_diameter_m"])

    def test_missing_or_mixed_ports_and_nonpositive_material_skip_reynolds(self):
        for change in ("missing","mixed","material"):
            with self.subTest(change=change):
                data=inventory()
                if change in {"missing","mixed"}: node(data,"Outlet")["selected_entity_ids"]=[]
                if change=="mixed": node(data,"Inlet").update(selected_entity_ids=[1,2],declared_entity_ids=[1,2])
                if change=="material": data["components"][0]["materials"][0]["density"]["value"]=-1
                result=run(data)
                self.assertEqual(next(r for r in result["rules"] if r["rule_id"]=="REYNOLDS_RISK")["status"],"skipped")

    def test_normalized_contract_rejects_inconsistent_geometry(self):
        for values in ({"bounding_box_m":[1,0,1,0,1,0]}, {"end_face_ids":[1]},
                       {"wall_face_ids":[1]}, {"pipe_diameter_m":None}):
            with self.subTest(values=values):
                model=flow.normalize(inventory());model["geometry"].update(values)
                with self.assertRaises(flow.ValidationError): flow.validate(model)

    def test_closed_pipe_default_wall_is_not_role_error(self):
        data=inventory();features=data["components"][0]["physics"][0]["features"]
        features[:]=[f for f in features if f["type"] not in {"Inlet","Outlet"}]
        node(data,"WallBC")["selected_entity_ids"]=[1,2,3]
        result=run(data)
        self.assertEqual(result["findings"],[])
        for code in ("MISSING_INLET","MISSING_OUTLET","REYNOLDS_RISK","FLOW_FACE_SELECTION_INCONSISTENT"):
            self.assertEqual(next(r for r in result["rules"] if r["rule_id"]==code)["status"],"skipped")

    def test_native_bbox_rounding_does_not_create_threshold_crossing(self):
        data=inventory();g=data["components"][0]["geometries"][0]
        g["three_dimensional_evidence"]["domains"][0]["bounding_box"]=[-.02500000037252903,.02500000037252903,-.02500000037252903,.02500000037252903,0,1]
        node(data,"Inlet")["evaluated_parameters"]["normal_velocity"]["value"]=.04
        result=run(data)
        self.assertEqual(result["model"]["geometry"]["pipe_diameter_m"],.05)
        self.assertNotIn("REYNOLDS_RISK",{f["code"] for f in result["findings"]})


if __name__ == "__main__":
    unittest.main()
