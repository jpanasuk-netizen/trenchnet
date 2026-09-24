/* TRENCHNET local chart helpers — no CDN. Canvas crosshair + brush-zoom. */
(function (global) {
  function nice(n) {
    if (n == null || isNaN(n)) return "—";
    if (Math.abs(n) >= 100) return n.toFixed(1);
    if (Math.abs(n) >= 1) return n.toFixed(3);
    return n.toFixed(5);
  }
  function Chart(canvas, opts) {
    this.cv = canvas;
    this.ctx = canvas.getContext("2d");
    this.opts = opts || {};
    this.series = []; // [{x,y,label?}]
    this.xMin = null; this.xMax = null; this.yMin = null; this.yMax = null;
    this.brush = null; // {x0,x1} in data space after brush
    this._hover = null;
    this._dragging = null;
    this._bind();
  }
  Chart.prototype.setSeries = function (pts) {
    this.series = (pts || []).slice().sort(function (a, b) { return a.x - b.x; });
    this._recomputeDomain();
    this.draw();
  };
  Chart.prototype._recomputeDomain = function () {
    var pts = this.series;
    if (!pts.length) { this.xMin = 0; this.xMax = 1; this.yMin = 0; this.yMax = 1; return; }
    var xs = pts.map(function (p) { return p.x; });
    var ys = pts.map(function (p) { return p.y; });
    this.xMin = this.brush ? this.brush.x0 : Math.min.apply(null, xs);
    this.xMax = this.brush ? this.brush.x1 : Math.max.apply(null, xs);
    if (this.xMax <= this.xMin) this.xMax = this.xMin + 1;
    var vis = pts.filter(function (p) { return p.x >= this.xMin && p.x <= this.xMax; }.bind(this));
    if (!vis.length) vis = pts;
    ys = vis.map(function (p) { return p.y; });
    this.yMin = Math.min.apply(null, ys);
    this.yMax = Math.max.apply(null, ys);
    if (this.yMax <= this.yMin) { this.yMax = this.yMin + 1e-9; this.yMin -= 1e-9; }
  };
  Chart.prototype._pad = function () { return { l: 56, r: 14, t: 28, b: 40 }; };
  Chart.prototype._map = function (p) {
    var pad = this._pad(), W = this.cv.width, H = this.cv.height;
    var x = pad.l + (p.x - this.xMin) / (this.xMax - this.xMin) * (W - pad.l - pad.r);
    var y = pad.t + (1 - (p.y - this.yMin) / (this.yMax - this.yMin)) * (H - pad.t - pad.b);
    return { x: x, y: y };
  };
  Chart.prototype._invX = function (cx) {
    var pad = this._pad(), W = this.cv.width;
    return this.xMin + (cx - pad.l) / Math.max(1, W - pad.l - pad.r) * (this.xMax - this.xMin);
  };
  Chart.prototype.draw = function () {
    var cv = this.cv, ctx = this.ctx, W = cv.width, H = cv.height;
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = "rgba(5,8,20,0.35)";
    ctx.fillRect(0, 0, W, H);
    var pad = this._pad();
    // axes
    ctx.strokeStyle = "rgba(0,180,255,0.25)";
    ctx.beginPath();
    ctx.moveTo(pad.l, pad.t); ctx.lineTo(pad.l, H - pad.b); ctx.lineTo(W - pad.r, H - pad.b);
    ctx.stroke();
    ctx.fillStyle = "rgba(223,233,255,0.65)";
    ctx.font = "11px ui-monospace, Consolas, monospace";
    ctx.fillText(nice(this.yMax), 4, pad.t + 10);
    ctx.fillText(nice(this.yMin), 4, H - pad.b);
    // axis titles (units from opts)
    ctx.fillStyle = "rgba(0,180,255,0.85)";
    ctx.font = "10px Segoe UI,sans-serif";
    var yTitle = this.opts.yLabel || "value";
    var xTitle = this.opts.xLabel || "time (CT)";
    ctx.save();
    ctx.translate(12, H / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText(yTitle, 0, 0);
    ctx.restore();
    ctx.fillText(xTitle, pad.l, H - 8);
    if (this.opts.title) {
      ctx.fillStyle = "#dfe9ff";
      ctx.font = "bold 12px Segoe UI,sans-serif";
      ctx.fillText(this.opts.title, pad.l, 16);
    }
    if (!this.series.length) {
      ctx.fillStyle = "rgba(223,233,255,0.45)";
      ctx.fillText("no series", pad.l + 8, pad.t + 20);
      return;
    }
    ctx.strokeStyle = this.opts.color || "#00B4FF";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    var started = false;
    for (var i = 0; i < this.series.length; i++) {
      var p = this.series[i];
      if (p.x < this.xMin || p.x > this.xMax) continue;
      var m = this._map(p);
      if (!started) { ctx.moveTo(m.x, m.y); started = true; }
      else ctx.lineTo(m.x, m.y);
    }
    ctx.stroke();
    // markers
    if (this.opts.markers) {
      this.opts.markers.forEach(function (mk) {
        if (mk.x < this.xMin || mk.x > this.xMax) return;
        var m = this._map(mk);
        var sell = (mk.side === "sell");
        ctx.fillStyle = sell ? "#ff5d8f" : "#39ffb0";
        ctx.beginPath();
        if (sell) {
          // red down-triangle = SELL
          ctx.moveTo(m.x, m.y + 5);
          ctx.lineTo(m.x - 5, m.y - 4);
          ctx.lineTo(m.x + 5, m.y - 4);
        } else {
          // green up-triangle = BUY
          ctx.moveTo(m.x, m.y - 5);
          ctx.lineTo(m.x - 5, m.y + 4);
          ctx.lineTo(m.x + 5, m.y + 4);
        }
        ctx.closePath(); ctx.fill();
      }.bind(this));
    }
    // always-visible mini legend when markers used
    if (this.opts.markers && this.opts.markers.length) {
      ctx.font = "10px Segoe UI,sans-serif";
      ctx.fillStyle = "#39ffb0"; ctx.fillText("▲ BUY", pad.l, pad.t + 4);
      ctx.fillStyle = "#ff5d8f"; ctx.fillText("▼ SELL", pad.l + 50, pad.t + 4);
    }
    // crosshair
    if (this._hover) {
      var h = this._hover;
      ctx.strokeStyle = "rgba(176,38,255,0.55)";
      ctx.setLineDash([4, 4]);
      ctx.beginPath(); ctx.moveTo(h.cx, pad.t); ctx.lineTo(h.cx, H - pad.b); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = "rgba(10,18,38,0.92)";
      ctx.strokeStyle = "#B026FF";
      var tip = (h.label || "") + "  y=" + nice(h.y);
      var tw = ctx.measureText(tip).width + 12;
      ctx.fillRect(Math.min(h.cx + 8, W - tw - 4), pad.t + 4, tw, 18);
      ctx.strokeRect(Math.min(h.cx + 8, W - tw - 4), pad.t + 4, tw, 18);
      ctx.fillStyle = "#dfe9ff";
      ctx.fillText(tip, Math.min(h.cx + 14, W - tw + 2), pad.t + 17);
    }
    // brush preview
    if (this._dragging) {
      var x0 = Math.min(this._dragging.a, this._dragging.b);
      var x1 = Math.max(this._dragging.a, this._dragging.b);
      ctx.fillStyle = "rgba(0,180,255,0.12)";
      ctx.fillRect(x0, pad.t, x1 - x0, H - pad.t - pad.b);
    }
  };
  Chart.prototype._nearest = function (cx) {
    var x = this._invX(cx), best = null, bestD = Infinity;
    for (var i = 0; i < this.series.length; i++) {
      var p = this.series[i];
      if (p.x < this.xMin || p.x > this.xMax) continue;
      var d = Math.abs(p.x - x);
      if (d < bestD) { bestD = d; best = p; }
    }
    return best;
  };
  Chart.prototype._bind = function () {
    var self = this;
    this.cv.addEventListener("mousemove", function (ev) {
      var r = self.cv.getBoundingClientRect();
      var cx = (ev.clientX - r.left) * (self.cv.width / r.width);
      if (self._dragging) { self._dragging.b = cx; self.draw(); return; }
      var p = self._nearest(cx);
      if (!p) { self._hover = null; self.draw(); return; }
      var m = self._map(p);
      self._hover = { cx: m.x, y: p.y, label: p.label || "" };
      self.draw();
    });
    this.cv.addEventListener("mouseleave", function () {
      self._hover = null; self._dragging = null; self.draw();
    });
    this.cv.addEventListener("mousedown", function (ev) {
      if (ev.button !== 0) return;
      var r = self.cv.getBoundingClientRect();
      var cx = (ev.clientX - r.left) * (self.cv.width / r.width);
      self._dragging = { a: cx, b: cx };
    });
    this.cv.addEventListener("mouseup", function () {
      if (!self._dragging) return;
      var x0 = self._invX(Math.min(self._dragging.a, self._dragging.b));
      var x1 = self._invX(Math.max(self._dragging.a, self._dragging.b));
      self._dragging = null;
      if (Math.abs(x1 - x0) < (self.xMax - self.xMin) * 0.02) { self.draw(); return; }
      self.brush = { x0: x0, x1: x1 };
      self._recomputeDomain(); self.draw();
    });
    this.cv.addEventListener("dblclick", function () {
      self.brush = null; self._recomputeDomain(); self.draw();
    });
  };
  global.TrenchCharts = { Chart: Chart, nice: nice };
})(window);
