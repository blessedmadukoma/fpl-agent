// Loaded in <head> without defer, so the saved theme and sidebar state apply before the first paint.
const root = document.documentElement;

function load(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function store(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {}
}

function describeSidebarButton(button) {
  const collapsed = root.dataset.sidebar === "collapsed";
  button.setAttribute("aria-expanded", String(!collapsed));
  button.ariaLabel = button.title = collapsed ? "Expand sidebar" : "Collapse sidebar";
}

if (load("theme")) root.dataset.theme = load("theme");
if (load("sidebar") === "collapsed") root.dataset.sidebar = "collapsed";

document.addEventListener("DOMContentLoaded", () => {
  describeSidebarButton(document.querySelector('[data-toggle="sidebar"]'));
});

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-toggle]");
  if (!button) return;

  if (button.dataset.toggle === "theme") {
    const dark = root.dataset.theme
      ? root.dataset.theme === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    store("theme", root.dataset.theme);
    return;
  }

  if (root.dataset.sidebar === "collapsed") delete root.dataset.sidebar;
  else root.dataset.sidebar = "collapsed";
  store("sidebar", root.dataset.sidebar || "expanded");
  describeSidebarButton(button);
});
