import com.comsol.model.Model;
import com.comsol.model.physics.PhysicsFeature;
import com.comsol.model.util.ModelUtil;
import java.util.Arrays;

/** Version-aware inventory and unsolved case builder; default main is read-only. */
public class ModelInventory {
  public static void main(String[] args) throws Exception {
    inspectFile("models/baseline_pipe_2d_laminar.mph", 10);
  }

  private static void inspectFile(String path, int loads) throws Exception {
    String first = null;
    for (int iteration = 0; iteration < loads; iteration++) {
      Model model = ModelUtil.load("Inventory", path);
      try {
        String snapshot = inspect(model);
        if (first == null) first = snapshot;
        else if (!first.equals(snapshot)) throw new IllegalStateException("Inventory changed across loads");
      } finally {
        ModelUtil.remove("Inventory");
      }
    }
    System.out.println("FLOWPILOT_INVENTORY_JSON " + first);
    System.out.println("FLOWPILOT_INVENTORY_VERIFIED " + loads);
  }

  public static String inspect(Model model) {
    StringBuilder json = new StringBuilder("{\"schema_version\":\"inventory-0.2\",\"comsol_version\":");
    json.append(quote(ModelUtil.getComsolVersion())).append(",\"multiphysics_tags\":[");
    String[] couplings = sorted(model.multiphysics().tags());
    for (int i = 0; i < couplings.length; i++) {
      if (i > 0) json.append(',');
      json.append(quote(couplings[i]));
    }
    json.append("],\"studies\":[");
    boolean separator = false;
    for (String study : sorted(model.study().tags())) {
      for (String tag : sorted(model.study(study).feature().tags())) {
        if (separator) json.append(',');
        separator = true;
        json.append("{\"study_tag\":").append(quote(study)).append(",\"feature_tag\":")
            .append(quote(tag)).append(",\"type\":").append(quote(model.study(study).feature(tag).getType()))
            .append(",\"enabled\":").append(model.study(study).feature(tag).isActive()).append('}');
      }
    }
    json.append("],\"components\":[");
    separator = false;
    for (String component : sorted(model.component().tags())) {
      if (separator) json.append(',');
      separator = true;
      json.append("{\"tag\":").append(quote(component)).append(",\"multiphysics_tags\":[");
      couplings = sorted(model.component(component).multiphysics().tags());
      for (int i = 0; i < couplings.length; i++) {
        if (i > 0) json.append(',');
        json.append(quote(couplings[i]));
      }
      json.append("],\"geometries\":[");
      boolean innerSeparator = false;
      for (String geometry : sorted(model.component(component).geom().tags())) {
        if (innerSeparator) json.append(',');
        innerSeparator = true;
        json.append("{\"tag\":").append(quote(geometry)).append(",\"dimension\":")
            .append(model.component(component).geom(geometry).getSDim()).append(",\"domain_count\":")
            .append(model.component(component).geom(geometry).getNDomains()).append(",\"boundary_count\":")
            .append(model.component(component).geom(geometry).getNBoundaries())
            .append(",\"axisymmetric\":").append(model.component(component).geom(geometry).isAxisymmetric())
            .append(",\"length_unit\":").append(quote(model.component(component).geom(geometry).lengthUnit()))
            .append(",\"bounding_box\":").append(Arrays.toString(model.component(component).geom(geometry).getBoundingBox()))
            .append(",\"feature_types\":[");
        String[] geometryTags = sorted(model.component(component).geom(geometry).feature().tags());
        for (int i = 0; i < geometryTags.length; i++) {
          if (i > 0) json.append(',');
          json.append(quote(model.component(component).geom(geometry).feature(geometryTags[i]).getType()));
        }
        String rotation = null;
        for (String geometryTag : geometryTags) {
          if ("Rectangle".equals(model.component(component).geom(geometry).feature(geometryTag).getType())) {
            rotation = model.component(component).geom(geometry).feature(geometryTag).getString("rot");
          }
        }
        json.append("],\"rectangle_rotation_expression\":").append(quote(rotation)).append('}');
      }
      json.append("],\"materials\":[");
      innerSeparator = false;
      for (String material : sorted(model.component(component).material().tags())) {
        if (innerSeparator) json.append(',');
        innerSeparator = true;
        json.append("{\"tag\":").append(quote(material)).append(",\"label\":")
            .append(quote(model.component(component).material(material).label()))
            .append(",\"enabled\":").append(model.component(component).material(material).isActive())
            .append(",\"domain_ids\":").append(Arrays.toString(model.component(component).material(material).selection().entities()))
            .append(",\"density\":");
        String density = model.component(component).material(material).propertyGroup("def").getString("density");
        String viscosity = model.component(component).material(material).propertyGroup("def").getString("dynamicviscosity");
        json.append(evaluate(model, density, "kg/m^3")).append(",\"dynamic_viscosity\":")
            .append(evaluate(model, viscosity, "Pa*s")).append('}');
      }
      json.append("],\"physics\":[");
      innerSeparator = false;
      for (String physics : sorted(model.component(component).physics().tags())) {
        if (innerSeparator) json.append(',');
        innerSeparator = true;
        json.append("{\"tag\":").append(quote(physics)).append(",\"type\":")
            .append(quote(model.component(component).physics(physics).getType()))
            .append(",\"enabled\":").append(model.component(component).physics(physics).isActive())
            .append(",\"study_active\":").append(studyActive(model, physics)).append(",\"features\":[");
        boolean featureSeparator = false;
        for (String tag : sorted(model.component(component).physics(physics).feature().tags())) {
          PhysicsFeature feature = model.component(component).physics(physics).feature(tag);
          if (featureSeparator) json.append(',');
          featureSeparator = true;
          int[] dimensions = feature.selection().dimension();
          String named = feature.selection().named();
          int[] declared = null;
          if (named != null && !named.isEmpty()) {
            declared = model.component(component).selection(named).entities();
          } else {
            declared = feature.selection().inputEntities();
          }
          json.append("{\"tag\":").append(quote(tag)).append(",\"label\":").append(quote(feature.label()))
              .append(",\"type\":").append(quote(feature.getType())).append(",\"enabled\":")
              .append(feature.isActive()).append(",\"selection_dimensions\":").append(Arrays.toString(dimensions))
              .append(",\"selected_entity_ids\":").append(Arrays.toString(feature.selection().entities()))
              .append(",\"declared_entity_ids\":").append(Arrays.toString(declared))
              .append(",\"named_selection\":").append(quote(named))
              .append(",\"whole_geometry_selection\":").append(feature.selection().isGeom())
              .append(",\"child_feature_count\":").append(feature.feature().tags().length)
              .append(",\"parameters\":{");
          boolean propertySeparator = false;
          String[] properties = ("FluidProperties".equals(feature.getType()) || "Inlet".equals(feature.getType()))
              ? sorted(feature.properties())
              : new String[] {"BoundaryCondition", "U0in", "u0", "p0", "SlipCondition", "WallCondition"};
          for (String property : properties) {
            if (!feature.hasProperty(property)) continue;
            if (propertySeparator) json.append(',');
            propertySeparator = true;
            json.append(quote(property)).append(':');
            String type = feature.getValueType(property);
            if ("StringArray".equals(type)) {
              json.append('[');
              String[] values = feature.getStringArray(property);
              for (int i = 0; i < values.length; i++) {
                if (i > 0) json.append(',');
                json.append(quote(values[i]));
              }
              json.append(']');
            } else if ("String".equals(type)) {
              json.append(quote(feature.getString(property)));
            } else {
              // Preserve unsupported property types explicitly rather than inventing values.
              json.append("{\"unread_value_type\":").append(quote(type)).append('}');
            }
          }
          json.append("},\"evaluated_parameters\":{");
          if ("Inlet".equals(feature.getType()) && "Velocity".equals(feature.getString("BoundaryCondition"))) {
            json.append("\"normal_velocity\":").append(evaluate(model, feature.getString("U0in"), "m/s"));
          } else if ("Outlet".equals(feature.getType()) && "PressureNoViscousStress".equals(feature.getString("BoundaryCondition"))) {
            json.append("\"pressure\":").append(evaluate(model, feature.getString("p0"), "Pa"));
          }
          json.append("}}");
        }
        json.append("]}");
      }
      json.append("]}");
    }
    return json.append("]}").toString();
  }

  /** Separate batch entry point selected by build_cases.ps1's generated driver. */
  public static void buildCases(String[] args) throws Exception {
    for (String name : new String[] {"missing_inlet", "missing_outlet", "selection_overlap", "reversed_inlet", "high_reynolds"}) {
      Model model = ModelUtil.load("Case", "models/baseline_pipe_2d_laminar.mph");
      try {
        if ("missing_inlet".equals(name)) model.component("comp1").physics("spf").feature().remove("inl1");
        if ("missing_outlet".equals(name)) model.component("comp1").physics("spf").feature().remove("out1");
        if ("selection_overlap".equals(name)) {
          model.component("comp1").physics("spf").create("out_conflict", "Outlet", 1);
          model.component("comp1").physics("spf").feature("out_conflict").selection().named("inlet");
          model.component("comp1").physics("spf").feature("out_conflict").set("p0", "p_out");
        }
        if ("reversed_inlet".equals(name)) model.param().set("Uin", "-0.01[m/s]");
        if ("high_reynolds".equals(name)) model.param().set("Uin", "0.1[m/s]");
        for (String solver : model.sol().tags()) model.sol(solver).clearSolutionData();
        model.label(name + ".mph");
        model.comments("FlowPilot synthetic configuration case; unsolved; expert/GUI review pending.");
        String path = "models/cases/" + name + ".mph";
        model.save(path);
      } finally {
        ModelUtil.remove("Case");
      }
      verifyCase(name);
    }
    System.out.println("FLOWPILOT_CASES_VERIFIED 5");
  }

  public static void inspectCases(String[] args) throws Exception {
    for (String name : new String[] {"missing_inlet", "missing_outlet", "selection_overlap", "reversed_inlet", "high_reynolds"}) {
      verifyCase(name);
    }
    System.out.println("FLOWPILOT_CASES_VERIFIED 5");
  }

  private static void verifyCase(String name) throws Exception {
    String first = null;
    for (int repeat = 0; repeat < 5; repeat++) {
      Model model = ModelUtil.load("Case", "models/cases/" + name + ".mph");
      try {
        String snapshot = inspect(model);
        if (first == null) first = snapshot;
        else if (!first.equals(snapshot)) throw new IllegalStateException("Case inventory drift: " + name);
      } finally {
        ModelUtil.remove("Case");
      }
    }
    System.out.println("FLOWPILOT_CASE_JSON {\"case_id\":\"" + name + "\",\"inventory\":" + first + "}");
  }

  private static boolean studyActive(Model model, String physics) {
    for (String study : model.study().tags()) {
      for (String tag : model.study(study).feature().tags()) {
        if ("Stationary".equals(model.study(study).feature(tag).getType())) {
          return model.study(study).feature(tag).activate(physics);
        }
      }
    }
    return false;
  }

  private static String evaluate(Model model, String expression, String unit) {
    String header = "{\"expression\":" + quote(expression) + ",\"unit\":" + quote(unit);
    try {
      double value = model.param().evaluate(expression, unit);
      if (!Double.isFinite(value)) throw new IllegalArgumentException("Non-finite value");
      return header + ",\"status\":\"resolved\",\"value\":" + value + "}";
    } catch (Exception error) {
      // Spatial fields, missing symbols and incompatible units stay unknown.
      return header + ",\"status\":\"unresolved\",\"value\":null}";
    }
  }

  private static String[] sorted(String[] tags) {
    Arrays.sort(tags);
    return tags;
  }

  private static String quote(String value) {
    if (value == null) return "null";
    StringBuilder json = new StringBuilder("\"");
    for (int i = 0; i < value.length(); i++) {
      char c = value.charAt(i);
      switch (c) {
        case '"': json.append("\\\""); break;
        case '\\': json.append("\\\\"); break;
        case '\n': json.append("\\n"); break;
        case '\r': json.append("\\r"); break;
        case '\t': json.append("\\t"); break;
        default:
          if (c < 32 || c > 126) json.append(String.format("\\u%04x", (int) c));
          else json.append(c);
      }
    }
    return json.append('"').toString();
  }
}
