// The generic app's organisation picker (E16-T11): find the organisation's portal, remember
// it on this device, and open it. White-label builds skip this page (server.url).
(function () {
  "use strict";

  var STRINGS = {
    "en-GB": {
      title: "Sign in to your tutoring organisation",
      label: "Your organisation's TutorTrack address",
      hint: "For example brightminds or brightminds.tutortrack.app",
      submit: "Continue",
      continueTo: "Continue to {name}",
      notFound: "We couldn't find that organisation. Check the address and try again.",
      offline: "You're offline. Connect to the internet and try again.",
      empty: "Enter your organisation's address.",
    },
    "en-US": {},
  };
  var lang = navigator.language === "en-US" ? "en-US" : "en-GB";
  function t(key, values) {
    var text = (STRINGS[lang] && STRINGS[lang][key]) || STRINGS["en-GB"][key];
    Object.keys(values || {}).forEach(function (k) {
      text = text.replace("{" + k + "}", values[k]);
    });
    return text;
  }
  document.documentElement.lang = lang;
  document.querySelectorAll("[data-i18n]").forEach(function (node) {
    node.textContent = t(node.getAttribute("data-i18n"));
  });

  var BASE = "tutortrack.app";
  var KEY = "tt-organisation";
  var form = document.getElementById("picker");
  var input = document.getElementById("org");
  var error = document.getElementById("error");

  function host(value) {
    var cleaned = value
      .trim()
      .toLowerCase()
      .replace(/^https?:\/\//, "")
      .split("/")[0];
    if (!cleaned) return "";
    if (!/^[a-z0-9.-]+$/.test(cleaned)) return "";
    return cleaned.indexOf(".") === -1 ? cleaned + "." + BASE : cleaned;
  }

  function open(target) {
    window.location.href = "https://" + target + "/portal/";
  }

  function remembered() {
    try {
      return JSON.parse(window.localStorage.getItem(KEY) || "null");
    } catch (e) {
      return null;
    }
  }

  var last = remembered();
  if (last && last.host) {
    var button = document.getElementById("continue");
    button.textContent = t("continueTo", { name: last.name || last.host });
    button.addEventListener("click", function () {
      open(last.host);
    });
    document.getElementById("last").hidden = false;
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    error.textContent = "";
    input.removeAttribute("aria-invalid");
    var target = host(input.value);
    if (!target) {
      error.textContent = t("empty");
      input.setAttribute("aria-invalid", "true");
      input.focus();
      return;
    }
    fetch("https://" + target + "/api/v1/public/branding", {
      headers: { Accept: "application/json" },
    })
      .then(function (response) {
        if (!response.ok) throw new Error("not-found");
        return response.json();
      })
      .then(function (brand) {
        try {
          window.localStorage.setItem(KEY, JSON.stringify({ host: target, name: brand.name }));
        } catch (e) {
          /* private mode: just open it */
        }
        open(target);
      })
      .catch(function (err) {
        error.textContent = navigator.onLine === false ? t("offline") : t("notFound");
        input.setAttribute("aria-invalid", "true");
        input.focus();
        return err;
      });
  });
})();
