import com.comsol.model.Model;
import com.comsol.model.physics.PhysicsFeature;
import com.comsol.model.util.ModelUtil;
import java.util.Arrays;

/** Read-only, version-aware inventory of the local baseline; no solver is run. */
public class ModelInventory {
  public static void main(String[] args) throws Exception {
    String first = null;
    for (int iteration = 0; iteration < 10; iteration++) {
      Model model = ModelUtil.load("Inventory", "models/baseline_pipe_2d_laminar.mph");
      try {
        String snapshot = inspect(model);
        if (first == null) first = snapshot;
        else if (!first.equals(snapshot)) throw new IllegalStateException("Inventory changed across loads");
      } finally {
        ModelUtil.remove("Inventory");
      }
    }
    System.out.println("FLOWPILOT_INVENTORY_JSON " + first);
    System.out.println("FLOWPILOT_INVENTORY_VERIFIED 10");
  }

  public static String inspect(Model model) {
    StringBuilder json = new StringBuilder("{\"schema_version\":\"inventory-0.1\",\"comsol_version\":");
    json.append(quote(ModelUtil.getComsolVersion())).append(",\"studies\":[");
    boolean separator = false;
    for (String study : sorted(model.study().tags())) {
      for (String tag : sorted(model.study(study).feature().tags())) {
        if (separator) json.append(',');
        separator = true;
        json.append("{\"study_tag\":").append(quote(study)).append(",\"feature_tag\":")
            .append(quote(tag)).append(",\"type\":").append(quote(model.study(study).feature(tag).getType())).append('}');
      }
    }
    json.append("],\"components\":[");
    separator = false;
    for (String component : sorted(model.component().tags())) {
      if (separator) json.append(',');
      separator = true;
      json.append("{\"tag\":").append(quote(component)).append(",\"geometries\":[");
      boolean innerSeparator = false;
      for (String geometry : sorted(model.component(component).geom().tags())) {
        if (innerSeparator) json.append(',');
        innerSeparator = true;
        json.append("{\"tag\":").append(quote(geometry)).append(",\"dimension\":")
            .append(model.component(component).geom(geometry).getSDim()).append(",\"domain_count\":")
            .append(model.component(component).geom(geometry).getNDomains()).append(",\"boundary_count\":")
            .append(model.component(component).geom(geometry).getNBoundaries()).append('}');
      }
      json.append("],\"physics\":[");
      innerSeparator = false;
      for (String physics : sorted(model.component(component).physics().tags())) {
        if (innerSeparator) json.append(',');
        innerSeparator = true;
        json.append("{\"tag\":").append(quote(physics)).append(",\"type\":")
            .append(quote(model.component(component).physics(physics).getType())).append(",\"features\":[");
        boolean featureSeparator = false;
        for (String tag : sorted(model.component(component).physics(physics).feature().tags())) {
          PhysicsFeature feature = model.component(component).physics(physics).feature(tag);
          if (featureSeparator) json.append(',');
          featureSeparator = true;
          int[] dimensions = feature.selection().dimension();
          json.append("{\"tag\":").append(quote(tag)).append(",\"label\":").append(quote(feature.label()))
              .append(",\"type\":").append(quote(feature.getType())).append(",\"enabled\":")
              .append(feature.isActive()).append(",\"selection_dimensions\":").append(Arrays.toString(dimensions))
              .append(",\"selected_entity_ids\":").append(Arrays.toString(feature.selection().entities()))
              .append(",\"parameters\":{");
          boolean propertySeparator = false;
          for (String property : new String[] {"BoundaryCondition", "U0in", "u0", "p0", "SlipCondition", "WallCondition"}) {
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
          json.append("}}");
        }
        json.append("]}");
      }
      json.append("]}");
    }
    return json.append("]}").toString();
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
