(function () {
  var el = document.getElementById("chart-data");
  if (!el) { return; }
  var data = JSON.parse(el.textContent);
  if (typeof Chart === "undefined") {
    console.warn("Chart.js failed to load (offline?). Tables are still available.");
    return;
  }
  Chart.defaults.color = "#94a3b8";
  Chart.defaults.borderColor = "#334155";

  function label(iso) {
    return data.bucket === "day" ? iso.slice(5, 10) : (data.bucket === "hour" ? iso.slice(5, 13) + "h" : iso.slice(11, 16));
  }

  new Chart(document.getElementById("timeChart"), {
    type: "line",
    data: {
      labels: data.time.map(function (p) { return label(p.t); }),
      datasets: [
        { label: "All logs", data: data.time.map(function (p) { return p.total; }), borderColor: "#38bdf8", tension: 0.25, pointRadius: 0 },
        { label: "Errors", data: data.time.map(function (p) { return p.errors; }), borderColor: "#f87171", tension: 0.25, pointRadius: 0 }
      ]
    },
    options: { interaction: { intersect: false, mode: "index" }, scales: { y: { beginAtZero: true } } }
  });

  new Chart(document.getElementById("serviceChart"), {
    type: "bar",
    data: {
      labels: data.services.map(function (s) { return s.service; }),
      datasets: [
        { label: "Logs", data: data.services.map(function (s) { return s.total; }), backgroundColor: "#38bdf8" },
        { label: "Errors", data: data.services.map(function (s) { return s.errors; }), backgroundColor: "#f87171" }
      ]
    },
    options: { indexAxis: "y", scales: { x: { beginAtZero: true } } }
  });

  new Chart(document.getElementById("statusChart"), {
    type: "doughnut",
    data: {
      labels: data.status_classes.map(function (s) { return s["class"]; }),
      datasets: [{ data: data.status_classes.map(function (s) { return s.count; }),
                   backgroundColor: ["#4ade80", "#38bdf8", "#fbbf24", "#f87171"], borderWidth: 0 }]
    }
  });
})();
