import com.comsol.model.Model;
import com.comsol.model.util.ModelUtil;
import java.util.Arrays;

/**
 * Reproducible generator for the FlowPilot 2D stationary laminar-flow baseline.
 *
 * <p>Compile with COMSOL Multiphysics 6.3 comsolcompile, then run the resulting
 * class with comsolbatch from the project root. It saves the baseline MPH model
 * and prints a verification report only after repeated-solve checks pass.</p>
 */
public class BaselinePipe2D {

  public static void main(String[] args) throws Exception {
    String output = "models/baseline_pipe_2d_laminar.mph";
    Model model = run();
    StringBuilder runs = new StringBuilder();
    double[] reference = metrics(model);
    appendMetrics(runs, 0, reference);
    model.save(output);
    for (int iteration = 1; iteration <= 3; iteration++) {
      ModelUtil.remove(model.tag());
      model = ModelUtil.load("Model", output);
      model.study("std1").run();
      double[] current = metrics(model);
      for (int j : new int[] {0, 1, 3, 6}) {
        double scale = Math.max(Math.abs(reference[j]), 1e-12);
        if (Math.abs(current[j] - reference[j]) / scale > 1e-5) {
          throw new IllegalStateException("Repeated solve drifted at metric " + j);
        }
      }
      runs.append(",\n");
      appendMetrics(runs, iteration, current);
    }
    StringBuilder version = new StringBuilder();
    for (char c : ModelUtil.getComsolVersion().toCharArray()) {
      if (c > 126) version.append(String.format("\\u%04x", (int) c));
      else version.append(c);
    }
    String json = "{\n  \"comsol_version\": \"" + version
        + "\",\n  \"inlet_boundary_ids\": " + Arrays.toString(model.component("comp1").selection("inlet").entities(1))
        + ",\n  \"outlet_boundary_ids\": " + Arrays.toString(model.component("comp1").selection("outlet").entities(1))
        + ",\n  \"wall_boundary_ids\": " + Arrays.toString(model.component("comp1").selection("walls").entities(1))
        + ",\n  \"reynolds_number\": " + model.param().evaluate("Re_expected")
        + ",\n  \"passed\": true,\n  \"runs\": [\n" + runs + "\n  ]\n}\n";
    System.out.println("FLOWPILOT_VERIFICATION_JSON " + json.replace("\n", ""));
    System.out.println("FLOWPILOT_BASELINE_VERIFIED");
  }

  public static Model run() {
    Model model = ModelUtil.create("Model");
    model.label("baseline_pipe_2d_laminar.mph");
    model.comments("FlowPilot ground-truth model: 2D stationary laminar pipe flow.");

    model.param().set("L", "1[m]", "Pipe length");
    model.param().set("H", "0.05[m]", "Pipe height");
    model.param().set("rho_ref", "1000[kg/m^3]", "Water density");
    model.param().set("mu_ref", "1e-3[Pa*s]", "Dynamic viscosity");
    model.param().set("Uin", "0.01[m/s]", "Normal inlet velocity");
    model.param().set("p_out", "0[Pa]", "Outlet gauge pressure");
    model.param().set("Re_expected", "rho_ref*Uin*H/mu_ref", "Expected Reynolds number (height-based)");

    model.component().create("comp1", true);
    model.component("comp1").label("2D Pipe Component");
    model.component("comp1").geom().create("geom1", 2);
    model.component("comp1").geom("geom1").label("Pipe Geometry");
    model.component("comp1").geom("geom1").lengthUnit("m");
    model.component("comp1").geom("geom1").create("r1", "Rectangle");
    model.component("comp1").geom("geom1").feature("r1").label("Pipe Domain");
    model.component("comp1").geom("geom1").feature("r1").set("size", new String[] {"L", "H"});
    model.component("comp1").geom("geom1").run();

    model.component("comp1").material().create("mat1", "Common");
    model.component("comp1").material("mat1").label("Water (Reference Properties)");
    model.component("comp1").material("mat1").selection().all();
    model.component("comp1").material("mat1").propertyGroup("def").set("density", "rho_ref");
    model.component("comp1").material("mat1").propertyGroup("def").set("dynamicviscosity", "mu_ref");

    // Select by geometry coordinates; COMSOL boundary IDs are not assumed.
    box(model, "inlet", -1e-8, 1e-8, -1e-8, 0.05000001);
    box(model, "outlet", 0.99999999, 1.00000001, -1e-8, 0.05000001);
    box(model, "bottom", -1e-8, 1.00000001, -1e-8, 1e-8);
    box(model, "top", -1e-8, 1.00000001, 0.04999999, 0.05000001);
    model.component("comp1").selection().create("walls", "Union");
    model.component("comp1").selection("walls").set("entitydim", 1);
    model.component("comp1").selection("walls").set("input", new String[] {"bottom", "top"});

    model.component("comp1").physics().create("spf", "LaminarFlow", "geom1");
    model.component("comp1").physics("spf").label("Laminar Flow");

    // Enumerate defaults: tags differ between API-generated and GUI models.
    String wallTag = null;
    for (String tag : model.component("comp1").physics("spf").feature().tags()) {
      String type = model.component("comp1").physics("spf").feature(tag).getType();
      System.out.println("FLOWPILOT_DEFAULT_FEATURE " + tag + " " + type);
      if ("Wall".equals(type) || "WallBC".equals(type)) wallTag = tag;
    }
    if (wallTag == null) {
      wallTag = "wall1";
      model.component("comp1").physics("spf").create(wallTag, "Wall", 1);
      model.component("comp1").physics("spf").feature(wallTag).selection().named("walls");
    }
    model.component("comp1").physics("spf").feature(wallTag).label("No-Slip Walls");

    model.component("comp1").physics("spf").create("inl1", "Inlet", 1);
    model.component("comp1").physics("spf").feature("inl1").label("Velocity Inlet");
    model.component("comp1").physics("spf").feature("inl1").selection().named("inlet");
    model.component("comp1").physics("spf").feature("inl1").set("BoundaryCondition", "Velocity");
    model.component("comp1").physics("spf").feature("inl1").set("U0in", "Uin");

    model.component("comp1").physics("spf").create("out1", "Outlet", 1);
    model.component("comp1").physics("spf").feature("out1").label("Pressure Outlet");
    model.component("comp1").physics("spf").feature("out1").selection().named("outlet");
    model.component("comp1").physics("spf").feature("out1").set("p0", "p_out");

    for (String tag : new String[] {"inl1", "out1", wallTag}) {
      System.out.println("FLOWPILOT_BOUNDARY " + tag + " "
          + model.component("comp1").physics("spf").feature(tag).getType() + " "
          + Arrays.toString(model.component("comp1").physics("spf").feature(tag).selection().entities(1)));
    }
    for (String tag : new String[] {"inlet", "outlet", "walls"}) {
      System.out.println("FLOWPILOT_SELECTION " + tag + " "
          + Arrays.toString(model.component("comp1").selection(tag).entities(1)));
    }

    model.component("comp1").mesh().create("mesh1");
    model.component("comp1").mesh("mesh1").label("Free Triangular Baseline Mesh (No Boundary Layers)");
    model.component("comp1").mesh("mesh1").autoMeshSize(5);
    model.component("comp1").mesh("mesh1").create("ftri1", "FreeTri");
    model.component("comp1").mesh("mesh1").feature("size").set("custom", "on");
    model.component("comp1").mesh("mesh1").feature("size").set("hmax", "H/20");
    model.component("comp1").mesh("mesh1").feature("size").set("hmin", "H/100");
    model.component("comp1").mesh("mesh1").run();

    model.study().create("std1");
    model.study("std1").label("Stationary Study");
    model.study("std1").create("stat", "Stationary");
    model.study("std1").feature("stat").activate("spf", true);
    model.study("std1").createAutoSequences("all");
    model.sol("sol1").feature("s1").set("stol", "1e-6");
    model.study("std1").run();

    numerical(model, "mass_in", "IntLine", "-rho_ref*(u*nx+v*ny)", "inlet");
    numerical(model, "mass_out", "IntLine", "rho_ref*(u*nx+v*ny)", "outlet");
    numerical(model, "pressure_in", "AvLine", "p", "inlet");
    numerical(model, "pressure_out", "AvLine", "p", "outlet");
    // Uniform inlet meets no-slip at discontinuous corner data. Exclude one H at each end.
    numerical(model, "wall_speed", "MaxLine", "if(x>H && x<L-H,spf.U,0[m/s])", "walls");
    numerical(model, "max_speed", "MaxSurface", "spf.U", null);
    numerical(model, "min_u", "MinSurface", "u", null);

    return model;
  }

  private static void box(Model model, String tag, double xmin, double xmax, double ymin, double ymax) {
    model.component("comp1").selection().create(tag, "Box");
    model.component("comp1").selection(tag).set("entitydim", 1);
    model.component("comp1").selection(tag).set("condition", "allvertices");
    model.component("comp1").selection(tag).set("xmin", xmin);
    model.component("comp1").selection(tag).set("xmax", xmax);
    model.component("comp1").selection(tag).set("ymin", ymin);
    model.component("comp1").selection(tag).set("ymax", ymax);
    if (model.component("comp1").selection(tag).entities(1).length != 1) {
      throw new IllegalStateException("Expected one boundary for " + tag);
    }
  }

  private static void numerical(Model model, String tag, String type, String expression, String selection) {
    model.result().numerical().create(tag, type);
    model.result().numerical(tag).set("expr", new String[] {expression});
    if (selection == null) model.result().numerical(tag).selection().all();
    else model.result().numerical(tag).selection().set(model.component("comp1").selection(selection).entities(1));
  }

  private static double value(Model model, String tag) {
    return model.result().numerical(tag).getReal()[0][0];
  }

  private static double[] metrics(Model model) {
    double in = value(model, "mass_in");
    double out = value(model, "mass_out");
    double error = Math.abs(in - out) / Math.max(Math.abs(in), Math.abs(out));
    double max = value(model, "max_speed");
    double wall = value(model, "wall_speed");
    double minU = value(model, "min_u");
    double drop = value(model, "pressure_in") - value(model, "pressure_out");
    if (!Double.isFinite(error) || !(in > 0) || !(out > 0) || error >= 1e-3
        || !Double.isFinite(max) || max <= 0 || max > 3 * model.param().evaluate("Uin")
        || !Double.isFinite(wall) || wall > 1e-8 || !Double.isFinite(minU) || minU < -1e-7
        || !Double.isFinite(drop) || drop <= 0) {
      throw new IllegalStateException("Physical validation failed: "
          + Arrays.toString(new double[] {in, out, error, max, wall, minU, drop}));
    }
    return new double[] {in, out, error, max, wall, minU, drop};
  }

  private static void appendMetrics(StringBuilder json, int index, double[] v) {
    json.append("    {\"run\": ").append(index)
        .append(", \"mass_in_kg_m_s\": ").append(v[0])
        .append(", \"mass_out_kg_m_s\": ").append(v[1])
        .append(", \"mass_relative_error\": ").append(v[2])
        .append(", \"max_speed_m_s\": ").append(v[3])
        .append(", \"wall_interior_speed_m_s\": ").append(v[4])
        .append(", \"min_u_m_s\": ").append(v[5])
        .append(", \"pressure_drop_pa\": ").append(v[6]).append("}");
  }
}
