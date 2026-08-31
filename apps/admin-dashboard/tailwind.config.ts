import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        graphite: "#202020",
        canvas: "#FFFFFF",
        ash: "#EFEFEF",
        fog: "#F5F5F5",
        ivory: "#EBE6DD",
        steel: "#4D4D4D",
        "slate-neutral": "#828282",
        mist: "#E8E8E8",
        ember: "#FF682C",
        brass: "#816729",
      },
      fontFamily: {
        display: ["PolySans", "Plus Jakarta Sans", "Inter", "system-ui", "sans-serif"],
        body: ["Inter", "system-ui", "sans-serif"],
      },
      borderRadius: {
        DEFAULT: "0px",
        none: "0px",
        sm: "0px",
        md: "0px",
        lg: "0px",
        xl: "12px",
        "2xl": "16px",
        full: "9999px",
      },
    },
  },
  plugins: [],
};

export default config;
