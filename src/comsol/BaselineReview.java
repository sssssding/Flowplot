import com.comsol.model.Model;
import com.comsol.model.util.ModelUtil;
import java.util.Arrays;

/** Export plots and cross-sections of the committed baseline's SAVED solution. */
public class BaselineReview {
  public static void main(String[] args) throws Exception {
    Model model = ModelUtil.load("Review", "input.mph");
    try {
      model.result().dataset().create("fp_saved", "Solution");
      model.result().dataset("fp_saved").set("solution", "sol1");
      double height = model.param().evaluate("H", "m");
      double inlet = model.param().evaluate("Uin", "m/s");
      StringBuilder json = new StringBuilder("{\"schema_version\":\"baseline-review-0.1\",");
      json.append("\"comsol_version\":").append(quote(ModelUtil.getComsolVersion()))
          .append(",\"solver_run\":false,\"height_m\":").append(height)
          .append(",\"inlet_velocity_m_s\":").append(inlet)
          .append(",\"metrics\":{");
      String[] tags = {"mass_in", "mass_out", "max_speed", "wall_speed", "min_u"};
      String[] names = {"mass_in_kg_m_s", "mass_out_kg_m_s", "max_speed_m_s",
                        "wall_interior_speed_m_s", "min_u_m_s"};
      for (int i = 0; i < tags.length; i++) {
        if (i > 0) json.append(',');
        json.append(quote(names[i])).append(':').append(value(model, tags[i]));
      }
      json.append(",\"pressure_drop_pa\":")
          .append(value(model, "pressure_in") - value(model, "pressure_out"));
      json.append("},\"sections\":[");
      model.result().numerical().create("fp_samples", "Interp");
      model.result().numerical("fp_samples").set("data", "fp_saved");
      model.result().numerical("fp_samples").set("expr", new String[] {"u", "v", "spf.U", "p"});
      model.result().numerical("fp_samples").set("unit", new String[] {"m/s", "m/s", "m/s", "Pa"});
      // No extrapolation: these are samples on or inside the saved fluid domain.
      model.result().numerical("fp_samples").set("ext", 0);
      double[] sections = {0.1, 0.25, 0.5, 0.9};
      model.result().create("fp_profiles", "PlotGroup1D");
      model.result("fp_profiles").label("Saved-solution velocity profiles");
      model.result("fp_profiles").set("titletype", "manual");
      model.result("fp_profiles").set("title", "Axial velocity profiles from saved stationary solution");
      for (int section = 0; section < sections.length; section++) {
        double x = sections[section];
        double[][] coordinates = new double[2][101];
        for (int i = 0; i < 101; i++) {
          coordinates[0][i] = x;
          coordinates[1][i] = height * i / 100.0;
        }
        model.result().numerical("fp_samples").setInterpolationCoordinates(coordinates);
        double[][][] samples = model.result().numerical("fp_samples").getData();
        if (samples.length != 4) throw new IllegalStateException("Expected four expressions");
        for (double[][] expression : samples) {
          if (expression.length != 1 || expression[0].length != 101) {
            throw new IllegalStateException("Expected one stationary solution and 101 samples");
          }
          for (double sample : expression[0]) {
            if (!Double.isFinite(sample)) throw new IllegalStateException("Non-finite field sample");
          }
        }
        if (section > 0) json.append(',');
        json.append("{\"x_m\":").append(x).append(",\"y_m\":")
            .append(Arrays.toString(coordinates[1])).append(",\"u_m_s\":")
            .append(Arrays.toString(samples[0][0])).append(",\"v_m_s\":")
            .append(Arrays.toString(samples[1][0])).append(",\"speed_m_s\":")
            .append(Arrays.toString(samples[2][0])).append(",\"pressure_pa\":")
            .append(Arrays.toString(samples[3][0])).append('}');
        String cut = "fp_cut" + section;
        String line = "fp_line" + section;
        model.result().dataset().create(cut, "CutLine2D");
        model.result().dataset(cut).set("data", "fp_saved");
        model.result().dataset(cut).set("genpoints", new double[][] {{x, 0}, {x, height}});
        model.result("fp_profiles").create(line, "LineGraph");
        model.result("fp_profiles").feature(line).set("data", cut);
        model.result("fp_profiles").feature(line).set("expr", "u");
        model.result("fp_profiles").feature(line).set("unit", "m/s");
        model.result("fp_profiles").feature(line).set("xdata", "expr");
        model.result("fp_profiles").feature(line).set("xdataexpr", "y/H");
        model.result("fp_profiles").feature(line).set("xdataunit", "1");
        model.result("fp_profiles").feature(line).set("legend", "on");
        model.result("fp_profiles").feature(line).set("legendmethod", "manual");
        model.result("fp_profiles").feature(line).set("legends", new String[] {"x = " + x + " m"});
        model.result("fp_profiles").feature(line).set("linewidth", 2);
      }
      json.append("]}");
      System.out.println("FLOWPILOT_REVIEW_JSON " + json);
      model.result().create("fp_velocity", "PlotGroup2D");
      model.result("fp_velocity").label("Saved-solution speed magnitude");
      model.result("fp_velocity").set("titletype", "manual");
      model.result("fp_velocity").set("title", "Speed magnitude (m/s), saved stationary solution");
      model.result("fp_velocity").set("data", "fp_saved");
      model.result("fp_velocity").create("surface", "Surface");
      model.result("fp_velocity").feature("surface").set("expr", "spf.U");
      model.result("fp_velocity").feature("surface").set("unit", "m/s");
      model.result("fp_velocity").run();
      model.result("fp_profiles").run();
      exportImage(model, "fp_velocity", "velocity.png", 1600, 400);
      exportImage(model, "fp_profiles", "profiles.png", 1200, 800);
      // Save only a new review artifact, never the input snapshot or original baseline.
      model.save("baseline_with_review_plots.mph");
      System.out.println("FLOWPILOT_REVIEW_VERIFIED");
    } finally {
      ModelUtil.remove("Review");
    }
  }

  private static void exportImage(Model model, String group, String filename, int width, int height) {
    String tag = group + "_image";
    model.result().export().create(tag, group, "Image");
    model.result().export(tag).set("imagetype", "png");
    model.result().export(tag).set("pngfilename", filename);
    model.result().export(tag).set("size", "manualweb");
    model.result().export(tag).set("unit", "px");
    model.result().export(tag).set("width", width);
    model.result().export(tag).set("height", height);
    model.result().export(tag).set("options1d", "on");
    model.result().export(tag).set("options2d", "on");
    model.result().export(tag).set("logo1d", "off");
    model.result().export(tag).set("logo2d", "off");
    model.result().export(tag).set("background", "color");
    model.result().export(tag).set("customcolor", new double[] {1, 1, 1});
    model.result().export(tag).set("zoomextents", "on");
    model.result().export(tag).run();
  }

  private static double value(Model model, String tag) {
    double result = model.result().numerical(tag).getReal()[0][0];
    if (!Double.isFinite(result)) throw new IllegalStateException("Non-finite metric " + tag);
    return result;
  }

  private static String quote(String value) {
    StringBuilder result = new StringBuilder("\"");
    for (char character : value.toCharArray()) {
      if (character < 32 || character > 126) result.append(String.format("\\u%04x", (int) character));
      else if (character == '"' || character == '\\') result.append('\\').append(character);
      else result.append(character);
    }
    return result.append('"').toString();
  }
}
