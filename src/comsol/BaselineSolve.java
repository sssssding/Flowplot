import com.comsol.model.Model;
import com.comsol.model.util.ModelUtil;

/** Cold-solve one committed baseline snapshot; never write the input file. */
public class BaselineSolve {
  public static void main(String[] args) throws Exception {
    ModelUtil.showProgress(true);
    Model model = ModelUtil.load("Solve", "input.mph");
    try {
      model.sol("sol1").clearSolutionData();
      if (!model.sol("sol1").isEmpty()) {
        throw new IllegalStateException("Saved solution was not cleared");
      }
      System.out.println("FLOWPILOT_SOLUTION_CLEARED");
      long start = System.nanoTime();
      model.sol("sol1").runAll();
      double seconds = (System.nanoTime() - start) / 1e9;
      if (model.sol("sol1").isEmpty()) {
        throw new IllegalStateException("Solver returned without solution data");
      }
      String[] keys = {"mass_in_kg_m_s", "mass_out_kg_m_s", "max_speed_m_s",
          "wall_interior_speed_m_s", "min_u_m_s", "pressure_drop_pa"};
      double[] values = {value(model, "mass_in"), value(model, "mass_out"),
          value(model, "max_speed"), value(model, "wall_speed"), value(model, "min_u"),
          value(model, "pressure_in") - value(model, "pressure_out")};
      StringBuilder json = new StringBuilder("{\"schema_version\":\"baseline-solve-0.1\",")
          .append("\"comsol_version\":").append(quote(ModelUtil.getComsolVersion()))
          .append(",\"solution_cleared_before_solve\":true,\"solution_present_after_solve\":true,")
          .append("\"solver_run\":true,\"solver_tag\":\"sol1\",\"solve_seconds\":").append(seconds)
          .append(",\"solver_warning\":").append(quote(model.sol("sol1").getWarningMessage()))
          .append(",\"solver_error\":").append(quote(model.sol("sol1").getErrorMessage()))
          .append(",\"metrics\":{");
      for (int i = 0; i < keys.length; i++) {
        if (!Double.isFinite(values[i])) throw new IllegalStateException("Non-finite metric " + keys[i]);
        if (i > 0) json.append(',');
        json.append(quote(keys[i])).append(':').append(values[i]);
      }
      json.append("}}");
      model.save("solved.mph");
      System.out.println("FLOWPILOT_SOLVE_JSON " + json);
      System.out.println("FLOWPILOT_SOLVE_VERIFIED");
    } finally {
      ModelUtil.remove(model.tag());
    }
  }

  private static double value(Model model, String tag) {
    return model.result().numerical(tag).getReal()[0][0];
  }

  private static String quote(String text) {
    StringBuilder out = new StringBuilder("\"");
    for (char c : (text == null ? "" : text).toCharArray()) {
      if (c == '"' || c == '\\') out.append('\\').append(c);
      else if (c < 32 || c > 126) out.append(String.format("\\u%04x", (int) c));
      else out.append(c);
    }
    return out.append('"').toString();
  }
}
