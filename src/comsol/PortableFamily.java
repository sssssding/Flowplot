import com.comsol.model.Model;
import com.comsol.model.util.ModelUtil;

/** Controlled development geometries only; never saves input.mph or solves here. */
public class PortableFamily {
  public static void main(String[] args) throws Exception {
    String[] names = {"short_narrow", "long_wide"};
    double[] lengths = {0.5, 2.0}, heights = {0.02, 0.1};
    for (int i=0; i<names.length; i++) {
      Model model = ModelUtil.load("Portable", "input.mph");
      try {
        model.param().set("L", lengths[i]+"[m]");
        model.param().set("H", heights[i]+"[m]");
        model.component("comp1").geom("geom1").run();
        double l=lengths[i], h=heights[i], e=1e-8;
        bounds(model,"inlet",-e,e,-e,h+e);
        bounds(model,"outlet",l-e,l+e,-e,h+e);
        bounds(model,"bottom",-e,l+e,-e,e);
        bounds(model,"top",-e,l+e,h-e,h+e);
        for (String tag : new String[]{"inlet","outlet","bottom","top"})
          if (model.component("comp1").selection(tag).entities(1).length != 1)
            throw new IllegalStateException("Invalid boundary selection");
        for (String tag : new String[]{"mass_in","pressure_in"})
          model.result().numerical(tag).selection().set(model.component("comp1").selection("inlet").entities(1));
        for (String tag : new String[]{"mass_out","pressure_out"})
          model.result().numerical(tag).selection().set(model.component("comp1").selection("outlet").entities(1));
        model.result().numerical("wall_speed").selection().set(model.component("comp1").selection("walls").entities(1));
        // Finer DEVELOPMENT mesh: the original narrow mesh failed the fixed mass gate.
        model.component("comp1").mesh("mesh1").feature("size").set("hmax","H/40");
        model.component("comp1").mesh("mesh1").feature("size").set("hmin","H/200");
        model.component("comp1").mesh("mesh1").run();
        model.sol("sol1").clearSolutionData();
        if (!model.sol("sol1").isEmpty()) throw new IllegalStateException("Old solution not cleared");
        model.save("models/"+names[i]+".mph");
        System.out.println("FLOWPLOT_PORTABLE_SAVED "+names[i]);
      } finally { ModelUtil.remove("Portable"); }
    }
    System.out.println("FLOWPLOT_PORTABLE_VERIFIED 2");
  }
  private static void bounds(Model m, String tag, double xmin,double xmax,double ymin,double ymax) {
    m.component("comp1").selection(tag).set("xmin",xmin);
    m.component("comp1").selection(tag).set("xmax",xmax);
    m.component("comp1").selection(tag).set("ymin",ymin);
    m.component("comp1").selection(tag).set("ymax",ymax);
  }
}
