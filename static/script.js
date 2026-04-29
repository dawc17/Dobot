 const PY =
        (Blockly.Python && Blockly.Python.pythonGenerator) || Blockly.Python;
      const PY_ORDER_NONE = PY?.ORDER_NONE ?? 99;
      const PY_ORDER_REL = PY?.ORDER_RELATIONAL ?? PY_ORDER_NONE;
      const PY_ORDER_NOT = PY?.ORDER_LOGICAL_NOT ?? PY_ORDER_NONE;

      function registerPyBlock(type, fn) {
        if (!PY) return;
        // Blockly 10+ expects generators in `forBlock`; older versions used direct assignment.
        if (PY.forBlock) PY.forBlock[type] = fn;
        PY[type] = fn;
      }

      function generatePyCode() {
        if (!PY || typeof PY.workspaceToCode !== "function") {
          throw new Error(
            "Blockly Python generator not available (check loaded Blockly scripts).",
          );
        }
        return PY.workspaceToCode(blocklyWorkspace);
      }

      function xmlTextToDom(text) {
        if (Blockly.Xml?.textToDom) return Blockly.Xml.textToDom(text);
        if (Blockly.utils?.xml?.textToDom) return Blockly.utils.xml.textToDom(text);
        throw new Error("Blockly XML parser not available.");
      }

      function pyStatementSuite(generator, block, inputName) {
        const stmt = generator.statementToCode(block, inputName);
        return stmt && stmt.trim() ? stmt : "  pass\n";
      }

      function namedPositionOptions() {
        let posMap = {};
        try {
          posMap = S?.positions || {};
        } catch (_) {
          posMap = {};
        }
        const names = Object.keys(posMap);
        if (!names.length) return [["(keine Position)", "__NONE__"]];
        names.sort((a, b) => a.localeCompare(b, "de"));
        return names.map((n) => [n, n]);
      }

      Blockly.Blocks["dobot_start"] = {
        init: function() {
          this.appendDummyInput().appendField("▶ START SCRIPT");
          this.setNextStatement(true, null);
          this.setColour(120);
          this.setTooltip("Marks the start of the program");
        }
      };
      registerPyBlock("dobot_start", function(block) {
        return "# --- SCRIPT START ---\n";
      });

      Blockly.Blocks["dobot_raw_python"] = {
        init: function() {
          const LabelField = Blockly.FieldLabelSerializable || Blockly.FieldLabel;
          this.appendDummyInput()
            .appendField("🐍 Raw Python")
            .appendField(new LabelField("(leer)"), "PREVIEW");
          this.setPreviousStatement(true, null);
          this.setNextStatement(true, null);
          this.setColour(260);
          this.setTooltip(
            "Enthält direkt geschriebenen Python-Code und wird 1:1 ausgeführt",
          );
        },
      };
      registerPyBlock("dobot_raw_python", function(block) {
        let code = String(block.data || "").replace(/\r\n/g, "\n");
        if (code && !code.endsWith("\n")) code += "\n";
        return code;
      });

      Blockly.Blocks["dobot_stop"] = {
        init: function() {
          this.appendDummyInput().appendField("🛑 STOP SCRIPT");
          this.setPreviousStatement(true, null);
          this.setColour(0);
          this.setTooltip("Immediately aborts the current program");
        }
      };
      registerPyBlock("dobot_stop", function(block) {
        return "core.seq_stop()\nraise Exception('Script stopped by block')\n";
      });

      Blockly.Blocks["dobot_log"] = {
        init: function() {
          this.appendValueInput("MSG").setCheck(null).appendField("Log");
          this.setPreviousStatement(true, null);
          this.setNextStatement(true, null);
          this.setColour(230);
        }
      };
      registerPyBlock("dobot_log", function(block, generator) {
        const g = generator || PY;
        var msg = g.valueToCode(block, "MSG", PY_ORDER_NONE) || '""';
        return "log(" + msg + ")\n";
      });

      Blockly.Blocks["dobot_move_to"] = {
        init: function() {
          this.appendDummyInput().appendField("Move To");
          this.appendValueInput("X").setCheck("Number").appendField("X");
          this.appendValueInput("Y").setCheck("Number").appendField("Y");
          this.appendValueInput("Z").setCheck("Number").appendField("Z");
          this.appendValueInput("R").setCheck("Number").appendField("R");
          this.setInputsInline(true);
          this.setPreviousStatement(true, null);
          this.setNextStatement(true, null);
          this.setColour(230);
        }
      };
      registerPyBlock("dobot_move_to", function(block, generator) {
        const g = generator || PY;
        var x = g.valueToCode(block, "X", PY_ORDER_NONE) || "0";
        var y = g.valueToCode(block, "Y", PY_ORDER_NONE) || "0";
        var z = g.valueToCode(block, "Z", PY_ORDER_NONE) || "0";
        var r = g.valueToCode(block, "R", PY_ORDER_NONE) || "0";
        return "sync_move_to(" + x + ", " + y + ", " + z + ", " + r + ")\n";
      });

      Blockly.Blocks["dobot_move_to_current"] = {
        init: function() {
          this.appendDummyInput()
            .appendField("Go to Position")
            .appendField("X")
            .appendField(new Blockly.FieldNumber(0, -1000, 1000, 0.1), "X")
            .appendField("Y")
            .appendField(new Blockly.FieldNumber(0, -1000, 1000, 0.1), "Y");
          this.appendDummyInput()
            .appendField("Z")
            .appendField(new Blockly.FieldNumber(0, -1000, 1000, 0.1), "Z")
            .appendField("R")
            .appendField(new Blockly.FieldNumber(0, -360, 360, 0.1), "R");
          this.setPreviousStatement(true, null);
          this.setNextStatement(true, null);
          this.setColour(230);
          this.setTooltip(
            "Automatically sets the current robot position when inserted",
          );
          this._seededFromLivePos = false;
        },
        onchange: function(event) {
          if (!event || this._seededFromLivePos) return;
          if (!this.workspace || this.workspace.isFlyout) return;
          const createEvt = Blockly.Events?.BLOCK_CREATE || "create";
          if (event.type !== createEvt) return;
          if (!Array.isArray(event.ids) || !event.ids.includes(this.id)) return;
          const pos = typeof S !== "undefined" ? S.pos : null;
          if (!pos) return;
          const fmt = (v) => {
            const n = Number(v);
            return Number.isFinite(n) ? String(Number(n.toFixed(2))) : "0";
          };
          this.setFieldValue(fmt(pos.X), "X");
          this.setFieldValue(fmt(pos.Y), "Y");
          this.setFieldValue(fmt(pos.Z), "Z");
          this.setFieldValue(fmt(pos.R), "R");
          this._seededFromLivePos = true;
        },
      };
      registerPyBlock("dobot_move_to_current", function(block) {
        const x = Number(block.getFieldValue("X")) || 0;
        const y = Number(block.getFieldValue("Y")) || 0;
        const z = Number(block.getFieldValue("Z")) || 0;
        const r = Number(block.getFieldValue("R")) || 0;
        return "sync_move_to(" + x + ", " + y + ", " + z + ", " + r + ")\n";
      });

      Blockly.Blocks["dobot_move_named_script"] = {
        init: function() {
          this.appendDummyInput()
            .appendField("Go to Named")
            .appendField(new Blockly.FieldDropdown(namedPositionOptions), "NAME");
          this.appendDummyInput()
            .appendField("dX")
            .appendField(new Blockly.FieldNumber(0, -1000, 1000, 0.1), "DX")
            .appendField("dY")
            .appendField(new Blockly.FieldNumber(0, -1000, 1000, 0.1), "DY");
          this.appendDummyInput()
            .appendField("dZ")
            .appendField(new Blockly.FieldNumber(0, -1000, 1000, 0.1), "DZ")
            .appendField("dR")
            .appendField(new Blockly.FieldNumber(0, -360, 360, 0.1), "DR");
          this.setPreviousStatement(true, null);
          this.setNextStatement(true, null);
          this.setColour(230);
          this.setTooltip("Fährt zu einer gespeicherten Named Position mit optionalem Offset");
        },
      };
      registerPyBlock("dobot_move_named_script", function(block) {
        const name = block.getFieldValue("NAME") || "__NONE__";
        if (name === "__NONE__") {
          return "log('No named position selected')\n";
        }
        const dx = Number(block.getFieldValue("DX")) || 0;
        const dy = Number(block.getFieldValue("DY")) || 0;
        const dz = Number(block.getFieldValue("DZ")) || 0;
        const dr = Number(block.getFieldValue("DR")) || 0;
        return (
          "sync_move_named(" +
          JSON.stringify(name) +
          ", " +
          dx +
          ", " +
          dy +
          ", " +
          dz +
          ", " +
          dr +
          ")\n"
        );
      });

      Blockly.Blocks["dobot_suction"] = {
        init: function() {
          this.appendDummyInput()
              .appendField("Suction")
              .appendField(new Blockly.FieldDropdown([["ON", "True"], ["OFF", "False"]]), "ON");
          this.setPreviousStatement(true, null);
          this.setNextStatement(true, null);
          this.setColour(230);
        }
      };
      registerPyBlock("dobot_suction", function(block) {
        var on = block.getFieldValue("ON");
        return "core.set_vacuum(" + on + ")\n";
      });

      Blockly.Blocks["dobot_wait"] = {
        init: function() {
          this.appendDummyInput().appendField("Wait");
          this.appendValueInput("SEC").setCheck("Number");
          this.appendDummyInput().appendField("seconds");
          this.setInputsInline(true);
          this.setPreviousStatement(true, null);
          this.setNextStatement(true, null);
          this.setColour(230);
        }
      };
      registerPyBlock("dobot_wait", function(block, generator) {
        const g = generator || PY;
        var sec = g.valueToCode(block, "SEC", PY_ORDER_NONE) || "0";
        return "sleep(" + sec + ")\n";
      });

      Blockly.Blocks["dobot_conveyor"] = {
        init: function() {
          this.appendDummyInput().appendField("Conveyor Belt");
          this.appendValueInput("SPEED").setCheck("Number").appendField("Speed (0.0-1.0)");
          this.appendValueInput("DIR").setCheck("Number").appendField("Direction (1/-1)");
          this.setInputsInline(true);
          this.setPreviousStatement(true, null);
          this.setNextStatement(true, null);
          this.setColour(230);
        }
      };
      registerPyBlock("dobot_conveyor", function(block, generator) {
        const g = generator || PY;
        var speed = g.valueToCode(block, "SPEED", PY_ORDER_NONE) || "0.5";
        var dir = g.valueToCode(block, "DIR", PY_ORDER_NONE) || "1";
        return "script_conveyor(" + speed + ", " + dir + ", 0)\n";
      });

      Blockly.Blocks["dobot_color_sensor"] = {
        init: function() {
          this.appendDummyInput()
              .appendField("Read Color")
              .appendField(new Blockly.FieldDropdown([["Red", "0"], ["Green", "1"], ["Blue", "2"]]), "COLOR")
              .appendField("port")
              .appendField(new Blockly.FieldDropdown([["GP1", "PORT_GP1"], ["GP2", "PORT_GP2"], ["GP4", "PORT_GP4"], ["GP5", "PORT_GP5"]]), "PORT");
          this.setOutput(true, "Boolean");
          this.setColour(230);
          this.setTooltip("Returns True if the selected color channel is detected on the chosen sensor port");
        }
      };
      registerPyBlock("dobot_color_sensor", function(block, generator) {
        const g = generator || PY;
        var c = block.getFieldValue("COLOR");
        var port = block.getFieldValue("PORT") || "PORT_GP2";
        if (g.definitions_) {
          g.definitions_["enable_color_" + port] =
            "core._color_enabled = Dobot." + port + "\ndevice.set_color(enable=True, port=Dobot." + port + ")";
        }
        return [
          "(device.get_color(port=Dobot." + port + ")[" + c + "] == 1)",
          PY_ORDER_REL,
        ];
      });

      Blockly.Blocks["dobot_ir_sensor"] = {
        init: function() {
          this.appendDummyInput()
              .appendField("IR/Movement Sensor")
              .appendField("port")
              .appendField(new Blockly.FieldDropdown([["GP4", "PORT_GP4"], ["GP1", "PORT_GP1"], ["GP2", "PORT_GP2"], ["GP5", "PORT_GP5"]]), "PORT");
          this.setOutput(true, "Boolean");
          this.setColour(60);
          this.setTooltip("Returns True when the IR/movement sensor detects an object on the selected port (GP4 is the common default)");
        }
      };
      registerPyBlock("dobot_ir_sensor", function(block, generator) {
        const g = generator || PY;
        var port = block.getFieldValue("PORT") || "PORT_GP4";
        if (g.definitions_) {
          g.definitions_["enable_ir_" + port] =
            "core._ir_enabled = Dobot." + port + "\ndevice.set_ir(enable=True, port=Dobot." + port + ")";
        }
        return [
          "(bool(device.get_ir(port=Dobot." + port + ")))",
          PY_ORDER_REL,
        ];
      });

      Blockly.Blocks["dobot_ir_sensor"] = {
        init: function() {
          this.appendDummyInput()
            .appendField("IR detected")
            .appendField(
              new Blockly.FieldDropdown([
                ["GP1", "GP1"],
                ["GP2", "GP2"],
                ["GP4", "GP4"],
                ["GP5", "GP5"],
              ]),
              "PORT",
            );
          this.setOutput(true, "Boolean");
          this.setColour(230);
        },
      };
      registerPyBlock("dobot_ir_sensor", function(block) {
        const port = block.getFieldValue("PORT") || "GP4";
        return ["ir_detected(" + JSON.stringify(port) + ")", PY_ORDER_NONE];
      });

      Blockly.Blocks["dobot_ir_debug"] = {
        init: function() {
          this.appendDummyInput()
            .appendField("IR debug")
            .appendField(
              new Blockly.FieldDropdown([
                ["GP1", "GP1"],
                ["GP2", "GP2"],
                ["GP4", "GP4"],
                ["GP5", "GP5"],
              ]),
              "PORT",
            );
          this.setPreviousStatement(true, null);
          this.setNextStatement(true, null);
          this.setColour(230);
          this.setTooltip("Schreibt den aktuellen IR-Zustand ins Log");
        },
      };
      registerPyBlock("dobot_ir_debug", function(block) {
        const port = block.getFieldValue("PORT") || "GP2";
        return "debug_ir(" + JSON.stringify(port) + ")\n";
      });

      Blockly.Blocks["dobot_ir_clause_detected"] = {
        init: function() {
          this.appendDummyInput()
            .appendField("IR")
            .appendField(
              new Blockly.FieldDropdown([
                ["GP1", "GP1"],
                ["GP2", "GP2"],
                ["GP4", "GP4"],
                ["GP5", "GP5"],
              ]),
              "PORT",
            )
            .appendField("is DETECTED");
          this.setOutput(true, "Boolean");
          this.setColour(210);
          this.setTooltip("Bedingung: IR Sensor erkennt ein Objekt");
        },
      };
      registerPyBlock("dobot_ir_clause_detected", function(block) {
        const port = block.getFieldValue("PORT") || "GP4";
        return ["ir_is_detected(" + JSON.stringify(port) + ")", PY_ORDER_NONE];
      });

      Blockly.Blocks["dobot_ir_clause_clear"] = {
        init: function() {
          this.appendDummyInput()
            .appendField("IR")
            .appendField(
              new Blockly.FieldDropdown([
                ["GP1", "GP1"],
                ["GP2", "GP2"],
                ["GP4", "GP4"],
                ["GP5", "GP5"],
              ]),
              "PORT",
            )
            .appendField("is CLEAR");
          this.setOutput(true, "Boolean");
          this.setColour(210);
          this.setTooltip("Bedingung: IR Sensor erkennt kein Objekt");
        },
      };
      registerPyBlock("dobot_ir_clause_clear", function(block) {
        const port = block.getFieldValue("PORT") || "GP4";
        return ["ir_is_clear(" + JSON.stringify(port) + ")", PY_ORDER_NOT];
      });

      Blockly.Blocks["dobot_not_stopped"] = {
        init: function() {
          this.appendDummyInput().appendField("Script not stopped");
          this.setOutput(true, "Boolean");
          this.setColour(120);
        }
      };
      registerPyBlock("dobot_not_stopped", function(block) {
        return ["(not core.seq_stop_evt.is_set())", PY_ORDER_NOT];
      });

      Blockly.Blocks["dobot_if"] = {
        init: function() {
          this.appendValueInput("COND")
            .setCheck("Boolean")
            .appendField("if");
          this.appendStatementInput("DO").appendField("do");
          this.setPreviousStatement(true, null);
          this.setNextStatement(true, null);
          this.setColour(120);
          this.setTooltip("Führt den Block nur aus, wenn die Bedingung wahr ist");
        }
      };
      registerPyBlock("dobot_if", function(block, generator) {
        const g = generator || PY;
        const cond = g.valueToCode(block, "COND", PY_ORDER_NONE) || "False";
        const body = pyStatementSuite(g, block, "DO");
        return "if " + cond + ":\n" + body;
      });

      Blockly.Blocks["dobot_if_else"] = {
        init: function() {
          this.appendValueInput("COND")
            .setCheck("Boolean")
            .appendField("if");
          this.appendStatementInput("DO").appendField("do");
          this.appendStatementInput("ELSE").appendField("else");
          this.setPreviousStatement(true, null);
          this.setNextStatement(true, null);
          this.setColour(120);
          this.setTooltip("Führt je nach Bedingung den if- oder else-Zweig aus");
        }
      };
      registerPyBlock("dobot_if_else", function(block, generator) {
        const g = generator || PY;
        const cond = g.valueToCode(block, "COND", PY_ORDER_NONE) || "False";
        const doBody = pyStatementSuite(g, block, "DO");
        const elseBody = pyStatementSuite(g, block, "ELSE");
        return "if " + cond + ":\n" + doBody + "else:\n" + elseBody;
      });

      Blockly.Blocks["dobot_if_elif_else"] = {
        init: function() {
          this.appendValueInput("COND1")
            .setCheck("Boolean")
            .appendField("if");
          this.appendStatementInput("DO1").appendField("do");
          this.appendValueInput("COND2")
            .setCheck("Boolean")
            .appendField("else if");
          this.appendStatementInput("DO2").appendField("do");
          this.appendStatementInput("ELSE").appendField("else");
          this.setPreviousStatement(true, null);
          this.setNextStatement(true, null);
          this.setColour(120);
          this.setTooltip("if / else if / else Verzweigung");
        }
      };
      registerPyBlock("dobot_if_elif_else", function(block, generator) {
        const g = generator || PY;
        const cond1 = g.valueToCode(block, "COND1", PY_ORDER_NONE) || "False";
        const cond2 = g.valueToCode(block, "COND2", PY_ORDER_NONE) || "False";
        const do1 = pyStatementSuite(g, block, "DO1");
        const do2 = pyStatementSuite(g, block, "DO2");
        const elseBody = pyStatementSuite(g, block, "ELSE");
        return (
          "if " +
          cond1 +
          ":\n" +
          do1 +
          "elif " +
          cond2 +
          ":\n" +
          do2 +
          "else:\n" +
          elseBody
        );
      });

      let blocklyWorkspace = null;
      const BLOCKLY_STATE_KEY = "dobot_hub_blockly";

      // ── State ─────────────────────────────────────────────────────────────────────
      const S = {
        connected: false,
        connecting: false,
        ports: [],
        portIndex: 0,
        pos: { X: 0, Y: 0, Z: 0, R: 0 },
        vacuum: false,
        convRunning: false,
        convDir: 1,
        convIface: 0,
        playing: false,
        paused: false,
        looping: false,
        current: -1,
        steps: [],
        selected: -1,
        jogStep: 20,
        positions: {},
        selectedPos: null,
      };

      const $ = (id) => document.getElementById(id);
      const esc = (s) =>
        String(s)
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;");

      // ── API ───────────────────────────────────────────────────────────────────────
      async function post(url, data) {
        const r = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data ?? {}),
        });
        if (r.status === 204) return null;
        return r.json();
      }
      async function del(url) {
        return (await fetch(url, { method: "DELETE" })).json();
      }
      async function put(url, data) {
        return (
          await fetch(url, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
          })
        ).json();
      }

      // ── SSE ───────────────────────────────────────────────────────────────────────
      function startSse() {
        const es = new EventSource("/events");
        es.onmessage = (e) => handle(JSON.parse(e.data));
        es.onerror = () => setStatus(false, false);
      }

      function handle(d) {
        switch (d.type) {
          case "state":
            applyState(d);
            break;
          case "pos":
            applyPos(d);
            break;
          case "log":
            addLog(d);
            break;
          case "steps":
            renderSteps(d.steps);
            break;
          case "seq_state":
            applySeqState(d);
            break;
          case "vacuum":
            setVacuum(d.on);
            break;
          case "conveyor":
            applyConveyor(d);
            break;
          case "ports":
            setPorts(d.ports, d.index);
            break;
          case "positions":
            applyPositions(d.positions);
            break;
        }
      }

      function applyState(d) {
        S.connected = d.connected;
        S.connecting = d.connecting;
        S.convRunning = d.conv_running;
        S.convDir = d.conv_direction;
        S.convIface = d.conv_interface;
        S.playing = d.seq_playing;
        S.paused = d.seq_paused;
        S.looping = d.seq_looping;
        S.current = d.seq_current;
        S.steps = d.steps ?? [];
        setPorts(d.ports, d.port_index);
        applyPos(d.pos);
        setStatus(d.connected, d.connecting);
        setVacuum(d.vacuum);
        updateConvBtns();
        renderSteps(S.steps);
        applySeqState(d);
        if (d.logs) d.logs.forEach(addLog);
        applyPositions(d.positions || {});
      }

      function applyPos(p) {
        if (!p) return;
        if (p.X !== undefined) S.pos = { X: p.X, Y: p.Y, Z: p.Z, R: p.R };
        $("px").textContent = S.pos.X.toFixed(2);
        $("py").textContent = S.pos.Y.toFixed(2);
        $("pz").textContent = S.pos.Z.toFixed(2);
        $("pr").textContent = S.pos.R.toFixed(2);
      }

      function setStatus(conn, busy) {
        const dot = $("dot"),
          txt = $("status-text"),
          btn = $("btn-connect");
        if (busy) {
          dot.className = "sdot warn";
          txt.textContent = "CONNECTING";
          btn.textContent = "Connecting…";
          btn.disabled = true;
        } else if (conn) {
          dot.className = "sdot ok";
          txt.textContent = "CONNECTED";
          btn.textContent = "Disconnect";
          btn.className = "danger";
          btn.disabled = false;
        } else {
          dot.className = "sdot";
          txt.textContent = "DISCONNECTED";
          btn.textContent = "Connect";
          btn.className = "";
          btn.disabled = false;
          if (irLogEnabled) {
            irLogEnabled = false;
            clearInterval(irLogTimer);
            irLogTimer = null;
            if ($("btn-ir-log")) {
              $("btn-ir-log").textContent = "IR Log: OFF";
              $("btn-ir-log").className = "ghost";
            }
          }
        }
      }

      function setPorts(ports, idx) {
        S.ports = ports ?? [];
        S.portIndex = idx ?? 0;
        const sel = $("port-select");
        sel.innerHTML = S.ports.length
          ? S.ports
              .map(
                (p, i) =>
                  `<option value="${i}"${i === S.portIndex ? " selected" : ""}>${p}</option>`,
              )
              .join("")
          : '<option value="">No ports</option>';
      }

      function setVacuum(on) {
        S.vacuum = on;
        const b = $("btn-vac");
        b.textContent = on ? "Vacuum ON" : "Vacuum OFF";
        b.className = on ? "success" : "";
      }

      function applyConveyor(d) {
        S.convRunning = d.running;
        S.convDir = d.direction;
        S.convIface = d.interface;
        updateConvBtns();
      }
      function updateConvBtns() {
        $("btn-crun").textContent = S.convRunning ? "Stop" : "Start";
        $("btn-crun").className = S.convRunning ? "danger" : "success";
        $("btn-cdir").textContent = S.convDir > 0 ? "Forward" : "Reverse";
        $("btn-ciface").textContent = `Iface: ${S.convIface}`;
      }

      function applySeqState(d) {
        S.playing = d.seq_playing ?? d.playing ?? S.playing;
        S.paused = d.seq_paused ?? d.paused ?? S.paused;
        S.looping = d.seq_looping ?? d.looping ?? S.looping;
        S.current = d.seq_current ?? d.current ?? S.current;
        const p = $("btn-play");
        if (S.playing && !S.paused) {
          p.textContent = "Pause";
          p.className = "";
        } else if (S.playing && S.paused) {
          p.textContent = "Resume";
          p.className = "success";
        } else {
          p.textContent = "Play";
          p.className = "success";
        }
        $("btn-loop").textContent = `Loop: ${S.looping ? "ON" : "OFF"}`;
        $("btn-loop").className = S.looping ? "success" : "ghost";
        renderSteps(null);
      }

      // ── Log ───────────────────────────────────────────────────────────────────────
      function addLog(e) {
        const el = $("log-entries");
        const row = document.createElement("div");
        row.className = `le ${e.level}`;
        row.innerHTML = `<span class="lts">${e.ts}</span><span class="lmsg">${esc(e.msg)}</span>`;
        el.appendChild(row);
        while (el.children.length > 300) el.removeChild(el.firstChild);
        el.scrollTop = el.scrollHeight;
      }

      // ── Named positions ───────────────────────────────────────────────────────
      function applyPositions(positions) {
        S.positions = positions || {};
        if (S.selectedPos && !(S.selectedPos in S.positions)) S.selectedPos = null;
        renderPositions();
      }

      function renderPositions() {
        const list = $("np-list");
        const names = Object.keys(S.positions);
        $("btn-np-del").style.display = S.selectedPos ? "" : "none";
        if (!names.length) {
          list.innerHTML = '<div style="color:var(--muted);font-size:11px;padding:8px;text-align:center">No saved positions</div>';
          return;
        }
        list.innerHTML = names.map(n => {
          const p = S.positions[n];
          const sel = n === S.selectedPos;
          return `<div class="np-row${sel ? " selected" : ""}" data-name="${esc(n)}">
            <span class="np-n">${esc(n)}</span>
            <span class="np-c">${p.x.toFixed(1)}, ${p.y.toFixed(1)}, ${p.z.toFixed(1)}</span>
          </div>`;
        }).join("");
        list.querySelectorAll(".np-row").forEach(row => {
          row.addEventListener("click", () => {
            const n = row.dataset.name;
            S.selectedPos = (S.selectedPos === n) ? null : n;
            if (S.selectedPos) $("np-name").value = S.selectedPos;
            renderPositions();
          });
        });
      }

      // ── Step list ─────────────────────────────────────────────────────────────────
      const COLORS = {
        move_to: "#3d7fe8",
        move_rel: "#5a9af0",
        suction: "#1fc46e",
        gripper: "#28d47e",
        wait: "#c89c20",
        home: "#6060a0",
        speed: "#4a85c8",
        set_io: "#c83848",
        conveyor_belt: "#c87820",
        conveyor_belt_distance: "#d06020",
        color_branch: "#b040c0",
        wait_for_color: "#9030a8",
        move_to_named: "#38b2d0",
        if_ir: "#c83848",
        if_state: "#2090a8",
        if_color: "#b040c0",
      };

      function slabel(s) {
        const t = s.type,
          p = s.params;
        if (t === "move_to")
          return `Move To (${p.x.toFixed(1)}, ${p.y.toFixed(1)}, ${p.z.toFixed(1)}, ${p.r.toFixed(1)})`;
        if (t === "move_rel")
          return `Move Rel (${p.x.toFixed(1)}, ${p.y.toFixed(1)}, ${p.z.toFixed(1)}, ${p.r.toFixed(1)})`;
        if (t === "suction") return `Suction ${p.on ? "ON" : "OFF"}`;
        if (t === "gripper") return `Gripper ${p.on ? "ON" : "OFF"}`;
        if (t === "wait") return `Wait ${p.seconds.toFixed(1)}s`;
        if (t === "home") return "Home";
        if (t === "speed") return `Speed ${p.velocity.toFixed(0)} mm/s`;
        if (t === "set_io") return `IO #${p.address} ${p.state ? "ON" : "OFF"}`;
        if (t === "conveyor_belt") {
          const d = p.direction > 0 ? "FWD" : "REV";
          const dur = p.duration > 0 ? ` ${p.duration.toFixed(1)}s` : " cont.";
          return `Belt ${Math.round(p.speed * 100)}% ${d}${dur}`;
        }
        if (t === "conveyor_belt_distance") {
          const d = p.direction > 0 ? "FWD" : "REV";
          return `Belt ${p.distance.toFixed(0)}mm@${p.speed.toFixed(0)}mm/s ${d}`;
        }
        if (t === "color_branch") {
          const parts = [];
          if (p.on_red > 0) parts.push(`R→${p.on_red}`);
          if (p.on_green > 0) parts.push(`G→${p.on_green}`);
          if (p.on_blue > 0) parts.push(`B→${p.on_blue}`);
          return `Color Branch ${parts.length ? parts.join(", ") : "(no branches set)"}`;
        }
        if (t === "move_to_named") {
          const offs = [["X","dx"],["Y","dy"],["Z","dz"],["R","dr"]]
            .filter(([,k]) => p[k]).map(([a,k]) => `d${a}${p[k]>0?"+":""}${p[k].toFixed(1)}`);
          return `→ '${p.name || "?"}'${offs.length ? " " + offs.join(" ") : ""}`;
        }
        if (t === "wait_for_color") {
          const colors = [
            p.wait_r ? "R" : null,
            p.wait_g ? "G" : null,
            p.wait_b ? "B" : null,
          ].filter(Boolean);
          const to = p.timeout > 0 ? ` ${p.timeout.toFixed(0)}s` : " ∞";
          return `Wait Color ${colors.join("|") || "?"}${to}`;
        }
        if (t === "if_ir") {
          const pnames = {0:"GP1",1:"GP2",2:"GP4",3:"GP5"};
          const port = pnames[p.port] ?? "GP?";
          return `If IR [${port}] ${p.on_detected ? `→${p.on_detected}` : "(no branch)"}`;
        }
        if (t === "if_state") {
          const labels = {suction_on:"Suction ON",suction_off:"Suction OFF",conveyor_on:"Conveyor ON",conveyor_off:"Conveyor OFF"};
          const cond = labels[p.condition] ?? p.condition ?? "?";
          const parts = [];
          if (p.on_true)  parts.push(`→${p.on_true}`);
          if (p.on_false) parts.push(`else→${p.on_false}`);
          return `If ${cond} ${parts.length ? parts.join(", ") : "(no branch)"}`;
        }
        if (t === "if_color") {
          const pnames = {0:"GP1",1:"GP2",2:"GP4",3:"GP5"};
          const port = pnames[p.port] ?? "GP?";
          const color = (p.color ?? "red")[0].toUpperCase() + (p.color ?? "red").slice(1);
          const parts = [];
          if (p.on_detected)     parts.push(`→${p.on_detected}`);
          if (p.on_not_detected) parts.push(`not→${p.on_not_detected}`);
          return `If ${color} [${port}] ${parts.length ? parts.join(", ") : "(no branch)"}`;
        }
        return t;
      }

      function renderSteps(steps) {
        if (steps != null) S.steps = steps;
        $("seq-cnt").textContent = `${S.steps.length} steps`;
        const list = $("seq-list");
        if (!S.steps.length) {
          list.innerHTML =
            '<div class="seq-empty">Use + buttons above to add steps</div>';
          return;
        }
        list.innerHTML = S.steps
          .map((s, i) => {
            const col = COLORS[s.type] || "#888";
            const cls =
              i === S.current ? "current" : i === S.selected ? "selected" : "";
            return `<div class="seq-row ${cls}" data-i="${i}">
      <span class="snum">${String(i + 1).padStart(2, "0")}</span>
      <span class="seqdot" style="background:${col}"></span>
      <span class="slbl">${esc(slabel(s))}</span>
    </div>`;
          })
          .join("");
        list.querySelectorAll(".seq-row").forEach((row) => {
          const idx = parseInt(row.dataset.i);
          row.addEventListener("click", () => {
            if (idx === S.selected) openEdit(idx);
            else {
              S.selected = idx;
              renderSteps(null);
            }
          });
          row.addEventListener("dblclick", () => openEdit(idx));
        });
      }

      // ── Step defaults ─────────────────────────────────────────────────────────────
      function defStep(type) {
        const pos = S.pos;
        const map = {
          move_to: { x: pos.X, y: pos.Y, z: pos.Z, r: pos.R },
          move_rel: { x: 0, y: 0, z: 0, r: 0 },
          suction: { on: true },
          gripper: { on: true },
          wait: { seconds: 1.0 },
          home: {},
          speed: { velocity: 100, acceleration: 100 },
          set_io: { address: 1, state: true },
          conveyor_belt: {
            speed: 0.5,
            direction: S.convDir,
            interface: S.convIface,
            duration: 2.0,
          },
          conveyor_belt_distance: {
            speed: 50,
            distance: 100,
            direction: S.convDir,
            interface: S.convIface,
          },
          color_branch: {
            port: 1,
            on_red: 0,
            on_green: 0,
            on_blue: 0,
            on_none: 0,
          },
          wait_for_color: {
            port: 1,
            wait_r: 1,
            wait_g: 0,
            wait_b: 0,
            timeout: 10,
          },
          move_to_named: {
            name: S.selectedPos || "",
            dx: 0,
            dy: 0,
            dz: 0,
            dr: 0,
          },
          if_ir: { port: 2, on_detected: 0 },
          if_state: { condition: "suction_on", on_true: 0, on_false: 0 },
          if_color: { port: 1, color: "red", on_detected: 0, on_not_detected: 0 },
        };
        const params = map[type] ?? {};
        if (type === "suction" || type === "gripper") {
          for (let i = S.steps.length - 1; i >= 0; i--) {
            if (S.steps[i].type === type) {
              params.on = !S.steps[i].params.on;
              break;
            }
          }
        }
        return { type, params };
      }

      async function addStep(type) {
        const step = defStep(type);
        const idx = S.selected >= 0 ? S.selected + 1 : S.steps.length;
        await post("/api/sequence/insert", { idx, step });
        S.selected = idx;
      }

      // ── Edit modal ────────────────────────────────────────────────────────────────
      const FIELDS = {
        move_to: [
          { k: "x", l: "X" },
          { k: "y", l: "Y" },
          { k: "z", l: "Z" },
          { k: "r", l: "R" },
        ],
        move_rel: [
          { k: "x", l: "X" },
          { k: "y", l: "Y" },
          { k: "z", l: "Z" },
          { k: "r", l: "R" },
        ],
        suction: [{ k: "on", l: "ON (1=on, 0=off)" }],
        gripper: [{ k: "on", l: "ON (1=on, 0=off)" }],
        wait: [{ k: "seconds", l: "Seconds" }],
        home: [],
        speed: [
          { k: "velocity", l: "Velocity (mm/s)" },
          { k: "acceleration", l: "Accel (mm/s²)" },
        ],
        set_io: [
          { k: "address", l: "Pin (1–22)" },
          { k: "state", l: "State (1=on, 0=off)" },
        ],
        conveyor_belt: [
          { k: "speed", l: "Speed (0.0–1.0)" },
          { k: "direction", l: "Direction (1=fwd, −1=rev)" },
          { k: "interface", l: "Interface (0 or 1)" },
          { k: "duration", l: "Duration sec (0=continuous)" },
        ],
        conveyor_belt_distance: [
          { k: "speed", l: "Speed (mm/s, 0–100)" },
          { k: "distance", l: "Distance (mm)" },
          { k: "direction", l: "Direction (1=fwd, −1=rev)" },
          { k: "interface", l: "Interface (0 or 1)" },
        ],
        color_branch: [
          { k: "port", l: "Sensor port (0=GP1 1=GP2 2=GP4 3=GP5)" },
          { k: "on_red", l: "Red detected → go to step# (0=continue)" },
          { k: "on_green", l: "Green detected → go to step# (0=continue)" },
          { k: "on_blue", l: "Blue detected → go to step# (0=continue)" },
          { k: "on_none", l: "Nothing detected → go to step# (0=continue)" },
        ],
        wait_for_color: [
          { k: "port", l: "Sensor port (0=GP1 1=GP2 2=GP4 3=GP5)" },
          { k: "wait_r", l: "Wait for Red (1=yes 0=no)" },
          { k: "wait_g", l: "Wait for Green (1=yes 0=no)" },
          { k: "wait_b", l: "Wait for Blue (1=yes 0=no)" },
          { k: "timeout", l: "Timeout seconds (0=infinite)" },
        ],
        move_to_named: [
          { k: "name", l: "Position name", type: "text" },
          { k: "dx", l: "dX offset (mm)" },
          { k: "dy", l: "dY offset (mm)" },
          { k: "dz", l: "dZ offset (mm)" },
          { k: "dr", l: "dR offset (°)" },
        ],
        if_ir: [
          { k: "port", l: "Sensor port", type: "select", options: [
            { value: "0", label: "GP1" },
            { value: "1", label: "GP2" },
            { value: "2", label: "GP4" },
            { value: "3", label: "GP5" },
          ]},
          { k: "on_detected", l: "Detected → go to step# (0=continue)" },
        ],
        if_state: [
          { k: "condition", l: "Condition", type: "select", options: [
            { value: "suction_on",   label: "Suction ON"    },
            { value: "suction_off",  label: "Suction OFF"   },
            { value: "conveyor_on",  label: "Conveyor ON"   },
            { value: "conveyor_off", label: "Conveyor OFF"  },
          ]},
          { k: "on_true",  l: "True → go to step# (0=continue)"  },
          { k: "on_false", l: "False → go to step# (0=continue)" },
        ],
        if_color: [
          { k: "port", l: "Sensor port", type: "select", options: [
            { value: "0", label: "GP1" },
            { value: "1", label: "GP2" },
            { value: "2", label: "GP4" },
            { value: "3", label: "GP5" },
          ]},
          { k: "color", l: "Color", type: "select", options: [
            { value: "red",   label: "Red"   },
            { value: "green", label: "Green" },
            { value: "blue",  label: "Blue"  },
          ]},
          { k: "on_detected",     l: "Detected → go to step# (0=continue)"     },
          { k: "on_not_detected", l: "Not detected → go to step# (0=continue)" },
        ],
      };
      let editIdx = -1;

      function openEdit(idx) {
        if (S.playing) return;
        editIdx = idx;
        const s = S.steps[idx];
        $("m-title").textContent = `Edit: ${s.type}`;
        const flds = FIELDS[s.type] ?? [];
        if (!flds.length) {
          $("m-fields").innerHTML =
            '<p style="color:var(--dim);font-size:12px;padding:4px 0">No editable parameters.</p>';
        } else {
          $("m-fields").innerHTML = flds
            .map((f) => {
              const v = s.params[f.k];
              if (f.type === "select") {
                const opts = f.options.map(o =>
                  `<option value="${esc(o.value)}"${v === o.value ? " selected" : ""}>${esc(o.label)}</option>`
                ).join("");
                return `<div class="frow"><label>${f.l}</label><select data-k="${f.k}">${opts}</select></div>`;
              }
              const isText = f.type === "text";
              const dv = isText ? (v ?? "") : (typeof v === "boolean" ? (v ? 1 : 0) : v);
              const attrs = isText ? "" : 'type="number" step="any"';
              return `<div class="frow"><label>${f.l}</label>
        <input ${attrs}${isText ? 'type="text"' : ""} data-k="${f.k}" value="${esc(String(dv))}"></div>`;
            })
            .join("");
        }
        $("edit-modal").classList.remove("hidden");
        const first = $("m-fields").querySelector("input");
        if (first) setTimeout(() => first.focus(), 50);
      }

      async function applyEdit() {
        if (editIdx < 0 || editIdx >= S.steps.length) {
          closeEdit();
          return;
        }
        const step = JSON.parse(JSON.stringify(S.steps[editIdx]));
        document.querySelectorAll("#m-fields select").forEach((sel) => {
          const k = sel.dataset.k, cur = step.params[k], v = sel.value;
          step.params[k] = typeof cur === "number" ? (Number.isInteger(cur) ? parseInt(v) : parseFloat(v)) : v;
        });
        document.querySelectorAll("#m-fields input").forEach((inp) => {
          const k = inp.dataset.k,
            cur = step.params[k],
            v = inp.value;
          if (inp.type === "text") step.params[k] = v;
          else if (typeof cur === "boolean")
            step.params[k] = v !== "0" && v.toLowerCase() !== "false";
          else if (typeof cur === "number" && Number.isInteger(cur))
            step.params[k] = Math.round(parseFloat(v));
          else step.params[k] = parseFloat(v);
        });
        await put(`/api/sequence/${editIdx}`, step);
        closeEdit();
      }
      function closeEdit() {
        editIdx = -1;
        $("edit-modal").classList.add("hidden");
      }

      // ── Load picker ───────────────────────────────────────────────────────────────
      async function openLoad() {
        const { files } = await (await fetch("/api/sequence/files")).json();
        const list = $("load-list");
        if (!files.length) {
          list.innerHTML =
            '<div style="color:var(--muted);padding:12px;font-size:12px">No saved sequences</div>';
        } else {
          list.innerHTML = files
            .map(
              (f) =>
                `<div class="li" data-f="${f}">${f.replace(".json", "")}</div>`,
            )
            .join("");
          list.querySelectorAll(".li").forEach((el) => {
            el.addEventListener("click", async () => {
              const r = await post("/api/sequence/load", {
                filename: el.dataset.f,
              });
              if (r.name) $("inp-name").value = r.name;
              $("load-modal").classList.add("hidden");
            });
          });
        }
        $("load-modal").classList.remove("hidden");
      }

      function ensureBlocklyWorkspace() {
        if (blocklyWorkspace) {
          reparentBlocklyFloatingUi();
          Blockly.svgResize(blocklyWorkspace);
          return blocklyWorkspace;
        }
        const scriptContainer = $("panel-script");
        if (scriptContainer) {
          const setParentContainer =
            Blockly.setParentContainer || Blockly.common?.setParentContainer;
          if (typeof setParentContainer === "function") {
            try {
              setParentContainer(scriptContainer);
            } catch (err) {
              console.warn("setParentContainer failed", err);
            }
          }
        }
        blocklyWorkspace = Blockly.inject("blocklyDiv", {
          toolbox: document.getElementById("toolbox"),
          scrollbars: true,
          theme: Blockly.Theme
            ? Blockly.Theme.defineTheme("dark", {
                base: Blockly.Themes.Classic,
                componentStyles: {
                  workspaceBackgroundColour: "#121212",
                  toolboxBackgroundColour: "#1e1e1e",
                  toolboxForegroundColour: "#eeeeee",
                  flyoutBackgroundColour: "#1a1a1a",
                  flyoutForegroundColour: "#ccc",
                  flyoutOpacity: 1,
                  scrollbarColour: "#333333",
                  insertionMarkerColour: "#fff",
                  insertionMarkerOpacity: 0.3,
                  scrollbarOpacity: 1,
                  cursorColour: "#d0d0d0",
                },
              })
            : undefined,
        });
        const storedState = localStorage.getItem(BLOCKLY_STATE_KEY);
        if (storedState) {
          try {
            const dom = xmlTextToDom(storedState);
            Blockly.Xml.domToWorkspace(dom, blocklyWorkspace);
          } catch (err) {
            console.warn("Failed to restore Blockly state", err);
          }
        }
        blocklyWorkspace.addChangeListener(() => {
          const dom = Blockly.Xml.workspaceToDom(blocklyWorkspace);
          const xmlText = Blockly.Xml.domToText(dom);
          localStorage.setItem(BLOCKLY_STATE_KEY, xmlText);
        });
        reparentBlocklyFloatingUi();
        return blocklyWorkspace;
      }

      function normalizeScriptCodeForWorkspace(code) {
        let c = String(code || "").replace(/\r\n/g, "\n");
        c = c.replace(/^\s*#\s*---\s*SCRIPT START\s*---\s*\n?/i, "");
        return c.trimEnd();
      }

      function rawCodePreview(code) {
        const line = String(code || "")
          .split("\n")
          .map((x) => x.trim())
          .find((x) => x.length > 0);
        if (!line) return "(leer)";
        return line.length > 42 ? `${line.slice(0, 39)}...` : line;
      }

      function applyPythonCodeToBlockly(code) {
        ensureBlocklyWorkspace();
        if (!blocklyWorkspace) return;
        const raw = normalizeScriptCodeForWorkspace(code);
        blocklyWorkspace.clear();

        const start = blocklyWorkspace.newBlock("dobot_start");
        start.initSvg();
        start.render();
        start.moveBy(24, 24);

        if (raw) {
          const rawBlock = blocklyWorkspace.newBlock("dobot_raw_python");
          rawBlock.data = raw;
          rawBlock.setFieldValue(rawCodePreview(raw), "PREVIEW");
          rawBlock.initSvg();
          rawBlock.render();
          rawBlock.moveBy(24, 110);
          if (start.nextConnection && rawBlock.previousConnection) {
            start.nextConnection.connect(rawBlock.previousConnection);
          }
        }

        Blockly.svgResize(blocklyWorkspace);
        const dom = Blockly.Xml.workspaceToDom(blocklyWorkspace);
        localStorage.setItem(BLOCKLY_STATE_KEY, Blockly.Xml.domToText(dom));
      }

      function reparentBlocklyFloatingUi() {
        const parent = $("panel-script");
        if (!parent) return;
        [".blocklyWidgetDiv", ".blocklyDropDownDiv", ".blocklyTooltipDiv"].forEach(
          (sel) => {
            document.querySelectorAll(sel).forEach((el) => {
              if (el.parentElement !== parent) parent.appendChild(el);
            });
          },
        );
      }

      function getScriptSnapshot() {
        const ta = $("script-editor");
        const editorVisible = ta && ta.style.display !== "none";
        let workspaceXml = localStorage.getItem(BLOCKLY_STATE_KEY) || "";
        let code = ta?.value || "";
        if (blocklyWorkspace) {
          const dom = Blockly.Xml.workspaceToDom(blocklyWorkspace);
          workspaceXml = Blockly.Xml.domToText(dom);
          if (!editorVisible) {
            try {
              code = generatePyCode();
            } catch (err) {
              console.warn("Script code generation failed while saving", err);
            }
          }
        }
        return { workspaceXml, code };
      }

      function clearScriptWorkspace() {
        ensureBlocklyWorkspace();
        if (blocklyWorkspace) {
          blocklyWorkspace.clear();
          Blockly.svgResize(blocklyWorkspace);
        }
        localStorage.removeItem(BLOCKLY_STATE_KEY);
        const ta = $("script-editor");
        ta.value = "";
        ta.dataset.dirty = "0";
        ta.style.display = "none";
        $("btn-toggle-code").textContent = "See Python Code";
      }

      async function openScriptLoad() {
        const { files } = await (await fetch("/api/scripts/files")).json();
        const list = $("script-load-list");
        if (!files.length) {
          list.innerHTML =
            '<div style="color:var(--muted);padding:12px;font-size:12px">No saved scripts</div>';
        } else {
          list.innerHTML = files
            .map((f) => `<div class="li" data-f="${f}">${f.replace(".json", "")}</div>`)
            .join("");
          list.querySelectorAll(".li").forEach((el) => {
            el.addEventListener("click", async () => {
              const r = await post("/api/scripts/load", {
                filename: el.dataset.f,
              });
              if (!r || !r.ok) return;
              ensureBlocklyWorkspace();
              if (r.workspace_xml) {
                try {
                  const dom = xmlTextToDom(r.workspace_xml);
                  if (Blockly.Xml.clearWorkspaceAndLoadFromXml) {
                    Blockly.Xml.clearWorkspaceAndLoadFromXml(dom, blocklyWorkspace);
                  } else {
                    blocklyWorkspace.clear();
                    Blockly.Xml.domToWorkspace(dom, blocklyWorkspace);
                  }
                  localStorage.setItem(BLOCKLY_STATE_KEY, r.workspace_xml);
                } catch (err) {
                  console.error("Failed to load script workspace", err);
                }
              } else {
                applyPythonCodeToBlockly(r.code || "");
              }
              $("script-editor").value = r.code || "";
              $("script-editor").dataset.dirty = "0";
              $("inp-script-name").value = r.name || el.dataset.f.replace(".json", "");
              $("script-load-modal").classList.add("hidden");
              if (blocklyWorkspace) Blockly.svgResize(blocklyWorkspace);
            });
          });
        }
        $("script-load-modal").classList.remove("hidden");
      }

      // ── Color sensor ──────────────────────────────────────────────────────────────
      let autoPoll = false,
        pollTimer = null;
      let irLogEnabled = false,
        irLogTimer = null;

      function setColorDots(r, g, b) {
        $("dot-r").classList.toggle("lit", !!r);
        $("dot-g").classList.toggle("lit", !!g);
        $("dot-b").classList.toggle("lit", !!b);
      }
      function setIrDot(det) {
        $("dot-ir").classList.toggle("lit", !!det);
      }

      async function readSensors() {
        if (!S.connected) return;
        try {
          const d = await post("/api/color_sensor", {
            port: $("color-port").value,
          });
          if (d && !d.error) setColorDots(d.r, d.g, d.b);
          const di = await post("/api/ir_sensor", { port: $("ir-port").value });
          if (di && !di.error) setIrDot(di.detected);
        } catch (_) {}
      }

      async function logIrStateOnce() {
        if (!S.connected) return;
        const port = $("ir-port").value;
        try {
          const di = await post("/api/ir_sensor", { port });
          if (di && !di.error) {
            setIrDot(di.detected);
            addLog({
              level: "INFO",
              ts: new Date().toLocaleTimeString(),
              msg: `IR ${port}: ${di.detected ? "DETECTED" : "clear"}`,
            });
          }
        } catch (_) {}
      }

      function toggleAutoPoll() {
        autoPoll = !autoPoll;
        $("btn-autopoll").textContent = `Auto: ${autoPoll ? "ON" : "OFF"}`;
        $("btn-autopoll").className = autoPoll ? "success" : "ghost";
        if (autoPoll) {
          readSensors();
          pollTimer = setInterval(readSensors, 500);
        } else {
          clearInterval(pollTimer);
          pollTimer = null;
        }
      }

      function toggleIrLog() {
        irLogEnabled = !irLogEnabled;
        $("btn-ir-log").textContent = `IR Log: ${irLogEnabled ? "ON" : "OFF"}`;
        $("btn-ir-log").className = irLogEnabled ? "success" : "ghost";
        if (irLogEnabled) {
          logIrStateOnce();
          irLogTimer = setInterval(logIrStateOnce, 500);
        } else {
          clearInterval(irLogTimer);
          irLogTimer = null;
        }
      }

      // ── Keyboard jog ──────────────────────────────────────────────────────────────
      const keys = new Set();
      let kbVx = 0,
        kbVy = 0;
      const KSTEP = 0.06;
      const noInput = () =>
        !["INPUT", "TEXTAREA", "SELECT"].includes(
          document.activeElement?.tagName,
        );

      document.addEventListener("keydown", (e) => {
        if (
          noInput() &&
          [
            "ArrowRight",
            "ArrowLeft",
            "ArrowUp",
            "ArrowDown",
            "PageUp",
            "PageDown",
          ].includes(e.code)
        )
          e.preventDefault();
        keys.add(e.code);
      });
      document.addEventListener("keyup", (e) => keys.delete(e.code));

      setInterval(() => {
        if (!noInput()) {
          kbVx = 0;
          kbVy = 0;
          return;
        }
        kbVx = keys.has("ArrowRight")
          ? Math.min(1, kbVx + KSTEP)
          : keys.has("ArrowLeft")
            ? Math.max(-1, kbVx - KSTEP)
            : 0;
        kbVy = keys.has("ArrowDown")
          ? Math.min(1, kbVy + KSTEP)
          : keys.has("ArrowUp")
            ? Math.max(-1, kbVy - KSTEP)
            : 0;
        const zsl = $("z-sl");
        if (keys.has("PageUp")) {
          zsl.value = Math.min(100, +zsl.value + 4);
          $("z-sv").textContent = zsl.value;
        }
        if (keys.has("PageDown")) {
          zsl.value = Math.max(-100, +zsl.value - 4);
          $("z-sv").textContent = zsl.value;
        }
      }, 16);

      // ── Jog loop at 30 fps ────────────────────────────────────────────────────────
      let jogBusy = false,
        lastJogAllZero = true;

      setInterval(() => {
        if (!S.connected || jogBusy) return;
        const vx = kbVx,
          vy = kbVy;
        const vz = parseFloat($("z-sl").value) / 100;
        const speed = parseFloat($("sp-sl").value);
        const allZero = vx === 0 && vy === 0 && vz === 0;
        if (allZero && lastJogAllZero) return;
        lastJogAllZero = allZero;
        jogBusy = true;
        fetch("/api/jog", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ vx, vy, vz, speed }),
        })
          .then(() => {
            jogBusy = false;
          })
          .catch(() => {
            jogBusy = false;
          });
      }, 33);

      // ── Init ──────────────────────────────────────────────────────────────────────
      document.addEventListener("DOMContentLoaded", () => {
        startSse();

        $("btn-refresh").onclick = () => post("/api/refresh");
        $("btn-connect").onclick = () => {
          if (S.connected) post("/api/disconnect");
          else {
            const idx = parseInt($("port-select").value) || 0;
            post("/api/connect", { port: S.ports[idx] || null });
          }
        };
        $("btn-home").onclick = () => post("/api/home");

        $("btn-curr").onclick = () => {
          $("ix").value = S.pos.X.toFixed(2);
          $("iy").value = S.pos.Y.toFixed(2);
          $("iz").value = S.pos.Z.toFixed(2);
          $("ir").value = S.pos.R.toFixed(2);
        };
        $("btn-move").onclick = () =>
          post("/api/move_to", {
            x: parseFloat($("ix").value),
            y: parseFloat($("iy").value),
            z: parseFloat($("iz").value),
            r: parseFloat($("ir").value),
          });

        document.querySelectorAll(".step-btn").forEach((b) => {
          b.onclick = () => {
            S.jogStep = parseFloat(b.dataset.step);
            document
              .querySelectorAll(".step-btn")
              .forEach((x) => x.classList.toggle("active", x === b));
          };
        });

        document.querySelectorAll("[data-axis]").forEach((b) => {
          b.onclick = () =>
            post("/api/jog_step", {
              axis: b.dataset.axis,
              sign: +b.dataset.sign,
              step: S.jogStep,
            });
        });

        $("z-sl").oninput = () => ($("z-sv").textContent = $("z-sl").value);
        $("z-sl").onmouseup = $("z-sl").ontouchend = () => {
          $("z-sl").value = 0;
          $("z-sv").textContent = "0";
          lastJogAllZero = false; // force one final stop send
        };

        $("sp-sl").oninput = () => ($("sp-sv").textContent = $("sp-sl").value);

        $("btn-vac").onclick = () => post("/api/vacuum", { on: !S.vacuum });
        $("btn-alm").onclick = () => post("/api/clear_alarms");

        $("cv-sl").oninput = () => ($("cv-sv").textContent = $("cv-sl").value);
        $("btn-cdir").onclick = () => {
          S.convDir = -S.convDir;
          $("btn-cdir").textContent = S.convDir > 0 ? "Forward" : "Reverse";
          if (S.convRunning) sendConv();
        };
        $("btn-crun").onclick = () => {
          if (S.convRunning)
            post("/api/conveyor", {
              speed: 0,
              direction: S.convDir,
              interface: S.convIface,
            });
          else sendConv();
        };
        $("btn-ciface").onclick = () => {
          S.convIface = 1 - S.convIface;
          $("btn-ciface").textContent = `Iface: ${S.convIface}`;
        };
        function sendConv() {
          post("/api/conveyor", {
            speed: parseInt($("cv-sl").value) / 100,
            direction: S.convDir,
            interface: S.convIface,
          });
        }

        // Named positions
        $("btn-np-save").onclick = () => {
          const name = $("np-name").value.trim();
          if (!name) return;
          post("/api/positions", { name });
          S.selectedPos = name;
        };
        $("btn-np-del").onclick = () => {
          if (!S.selectedPos) return;
          fetch(`/api/positions/${encodeURIComponent(S.selectedPos)}`, { method: "DELETE" });
          S.selectedPos = null;
          $("np-name").value = "";
        };
        $("btn-np-go").onclick = () => {
          if (!S.selectedPos) return;
          post(`/api/positions/${encodeURIComponent(S.selectedPos)}/go`, {
            dx: parseFloat($("np-dx").value) || 0,
            dy: parseFloat($("np-dy").value) || 0,
            dz: parseFloat($("np-dz").value) || 0,
            dr: 0,
          });
        };

        $("btn-read-sensor").onclick = readSensors;
        $("btn-autopoll").onclick = toggleAutoPoll;
        $("btn-ir-log").onclick = toggleIrLog;

        document
          .querySelectorAll(".add")
          .forEach((b) => (b.onclick = () => addStep(b.dataset.type)));

        // Slett steg med Delete-tasten og flytt steg med piltaster
        document.addEventListener("keydown", (e) => {
          const tag = document.activeElement?.tagName;
          if (tag === "INPUT" || tag === "TEXTAREA") return;
          // Slett steg
          if (e.key === "Delete" && S.selected >= 0) {
            del(`/api/sequence/${S.selected}`);
            S.selected = Math.max(-1, S.selected - 1);
            return;
          }
          if ((e.key === "ArrowUp" || e.key === "Up") && S.selected > 0) {
            post("/api/sequence/move", { idx: S.selected, delta: -1 });
            S.selected--;
            renderSteps(null);
            e.preventDefault();
            return;
          }
          // Flytt steg ned
          if ((e.key === "ArrowDown" || e.key === "Down") && S.selected < S.steps.length - 1 && S.selected >= 0) {
            post("/api/sequence/move", { idx: S.selected, delta: 1 });
            S.selected++;
            renderSteps(null);
            e.preventDefault();
            return;
          }
        });

        $("btn-del").onclick = () => {
          if (S.selected < 0) return;
          del(`/api/sequence/${S.selected}`);
          S.selected = Math.max(-1, S.selected - 1);
        };
        $("btn-up").onclick = () => {
          if (S.selected > 0) {
            post("/api/sequence/move", { idx: S.selected, delta: -1 });
            S.selected--;
          }
        };
        $("btn-dn").onclick = () => {
          if (S.selected < S.steps.length - 1) {
            post("/api/sequence/move", { idx: S.selected, delta: 1 });
            S.selected++;
          }
        };
        $("btn-dup").onclick = () => {
          if (S.selected >= 0) {
            post(`/api/sequence/${S.selected}/dup`);
            S.selected++;
          }
        };

        // Script Editor Tabs
        const scriptPanel = $("panel-script");
        const btnScriptFs = $("btn-script-fullscreen");

        const isScriptFullscreen = () =>
          document.fullscreenElement === scriptPanel ||
          document.webkitFullscreenElement === scriptPanel;

        const updateScriptFsUi = () => {
          const on = isScriptFullscreen();
          btnScriptFs.textContent = on ? "Exit Fullscreen" : "Fullscreen";
          btnScriptFs.className = on ? "danger" : "ghost";
          reparentBlocklyFloatingUi();
          if (blocklyWorkspace) Blockly.svgResize(blocklyWorkspace);
        };

        const enterScriptFullscreen = async () => {
          if (scriptPanel.requestFullscreen) {
            await scriptPanel.requestFullscreen();
            return;
          }
          if (scriptPanel.webkitRequestFullscreen) {
            scriptPanel.webkitRequestFullscreen();
            return;
          }
          addLog({
            level: "WARN",
            ts: new Date().toLocaleTimeString(),
            msg: "Fullscreen API not supported in this browser.",
          });
        };

        const exitScriptFullscreen = async () => {
          if (document.exitFullscreen && document.fullscreenElement) {
            await document.exitFullscreen();
            return;
          }
          if (document.webkitExitFullscreen && document.webkitFullscreenElement) {
            document.webkitExitFullscreen();
          }
        };

        btnScriptFs.onclick = async () => {
          try {
            if (isScriptFullscreen()) await exitScriptFullscreen();
            else await enterScriptFullscreen();
            reparentBlocklyFloatingUi();
            updateScriptFsUi();
          } catch (err) {
            console.error("Fullscreen toggle failed", err);
          }
        };

        document.addEventListener("fullscreenchange", updateScriptFsUi);
        document.addEventListener("webkitfullscreenchange", updateScriptFsUi);
        window.addEventListener("resize", () => {
          if (blocklyWorkspace) Blockly.svgResize(blocklyWorkspace);
        });

        $("tab-seq-btn").onclick = async () => {
          if (isScriptFullscreen()) await exitScriptFullscreen();
          $("tab-seq-btn").className = "active";
          $("tab-script-btn").className = "ghost";
          $("panel-seq").style.display = "flex";
          $("panel-script").style.display = "none";
        };
        $("tab-script-btn").onclick = () => {
          $("tab-script-btn").className = "active";
          $("tab-seq-btn").className = "ghost";
          $("panel-seq").style.display = "none";
          $("panel-script").style.display = "flex";
          ensureBlocklyWorkspace();
        };
        $("btn-run-script").onclick = () => {
          try {
            let code;
            const ta = $("script-editor");
            const editorVisible = ta.style.display !== "none";
            if (editorVisible) {
              code = ta.value;
            } else if (blocklyWorkspace) {
              code = generatePyCode();
            } else {
              code = ta.value;
            }
            post("/api/run_script", { code: code });
          } catch (err) {
            const msg = err?.message || String(err);
            addLog({
              level: "ERROR",
              ts: new Date().toLocaleTimeString(),
              msg: `Blockly code generation failed: ${msg}`,
            });
            console.error("Blockly code generation failed", err);
          }
        };
        $("btn-toggle-code").onclick = () => {
          const ta = $("script-editor");
          if (ta.style.display === "none") {
            ta.style.display = "block";
            $("btn-toggle-code").textContent = "Hide Python Code";
            if (ta.dataset.dirty !== "1" && blocklyWorkspace) {
              try {
                ta.value = generatePyCode();
                ta.dataset.dirty = "0";
              } catch (err) {
                ta.value = `# Failed to generate code:\n# ${
                  err?.message || String(err)
                }`;
                ta.dataset.dirty = "0";
              }
            }
          } else {
            if (ta.dataset.dirty === "1") {
              applyPythonCodeToBlockly(ta.value);
              ta.dataset.dirty = "0";
              try {
                ta.value = generatePyCode();
              } catch (_) {}
            }
            ta.style.display = "none";
            $("btn-toggle-code").textContent = "See Python Code";
          }
        };
        $("script-editor").dataset.dirty = "0";
        $("script-editor").addEventListener("input", () => {
          $("script-editor").dataset.dirty = "1";
        });
        $("btn-apply-code").onclick = () => {
          const ta = $("script-editor");
          applyPythonCodeToBlockly(ta.value);
          ta.dataset.dirty = "0";
          try {
            ta.value = generatePyCode();
          } catch (_) {}
        };
        $("btn-stop-script").onclick = () => {
          post("/api/sequence/stop"); // reuse existing stop which cancels everything
        };
        $("btn-script-save").onclick = async () => {
          const name = $("inp-script-name").value.trim();
          if (!name) return;
          ensureBlocklyWorkspace();
          const snap = getScriptSnapshot();
          const r = await post("/api/scripts/save", {
            name,
            workspace_xml: snap.workspaceXml,
            code: snap.code,
          });
          if (r?.name) $("inp-script-name").value = r.name;
        };
        $("btn-script-load").onclick = openScriptLoad;
        $("btn-script-clear").onclick = () => {
          clearScriptWorkspace();
        };

        document.addEventListener("keydown", (e) => {
          if (e.altKey && e.key === "r") {
            $("btn-run-script").click();
            e.preventDefault();
          }
        });

        $("btn-play").onclick = () =>
          post(S.playing ? "/api/sequence/pause" : "/api/sequence/play");
        $("btn-stop").onclick = () => post("/api/sequence/stop");
        $("btn-loop").onclick = async () => {
          const r = await post("/api/sequence/loop");
          S.looping = r.looping;
          $("btn-loop").textContent = `Loop: ${S.looping ? "ON" : "OFF"}`;
          $("btn-loop").className = S.looping ? "success" : "ghost";
        };

        $("btn-save").onclick = () =>
          post("/api/sequence/save", {
            name: $("inp-name").value.trim() || "untitled",
          });
        $("btn-load").onclick = openLoad;
        $("btn-clr").onclick = () => {
          post("/api/sequence/clear");
          S.selected = -1;
        };

        $("m-apply").onclick = applyEdit;
        $("m-cancel").onclick = closeEdit;
        $("edit-modal").onclick = (e) => {
          if (e.target === $("edit-modal")) closeEdit();
        };
        $("edit-modal").addEventListener("keydown", (e) => {
          if (e.key === "Enter") applyEdit();
          if (e.key === "Escape") closeEdit();
        });

        $("lm-cancel").onclick = () => $("load-modal").classList.add("hidden");
        $("load-modal").onclick = (e) => {
          if (e.target === $("load-modal"))
            $("load-modal").classList.add("hidden");
        };
        $("slm-cancel").onclick = () =>
          $("script-load-modal").classList.add("hidden");
        $("script-load-modal").onclick = (e) => {
          if (e.target === $("script-load-modal"))
            $("script-load-modal").classList.add("hidden");
        };
      });