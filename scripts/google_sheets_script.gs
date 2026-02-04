function getMonthStartRows(sheet) {
  const rows = [];
  const start = 3;
  const step = 23;
  for (let i = 0; i < 12; i++) {
    const row = start + step * i;
    if (row <= sheet.getLastRow()) rows.push(row);
  }
  return rows;
}

function dateKey(value) {
  let d = null;
  if (Object.prototype.toString.call(value) === '[object Date]' && !isNaN(value)) {
    d = value;
  } else if (typeof value === 'number') {
    d = new Date(Math.round((value - 25569) * 86400 * 1000));
  } else if (typeof value === 'string' && value) {
    const parsed = new Date(value);
    if (!isNaN(parsed)) d = parsed;
  }
  if (!d) return null;
  return Utilities.formatDate(d, Session.getScriptTimeZone(), 'yyyy-MM-dd');
}

function setupHabitSheet() {
  const ss = SpreadsheetApp.getActive();
  const grid = ss.getSheetByName('Habits Tracker 2026');
  const raw = ss.getSheetByName('raw_trackers');
  if (!grid || !raw) return;

  const trackerData = raw.getRange(2, 1, raw.getLastRow() - 1, 3).getValues();
  const trackers = trackerData.filter(r => r[0] && r[1] && r[2]);
  if (!trackers.length) return;

  const startCol = 10; // J
  const endCol = 40; // AN
  const nameCol = 9; // I

  const listTimeCount = [0, 0.5, 1, 1.5, 2, 3, 4, 5, 6, 7, 8, 10, 12];
  const listScale = [1,2,3,4,5,6,7,8,9,10];

  const monthStarts = getMonthStartRows(grid);
  monthStarts.forEach(startRow => {
    trackers.forEach((t, idx) => {
      const row = startRow + idx;
      const name = t[1];
      const type = t[2];

      grid.getRange(row, nameCol).setValue(name);

      const range = grid.getRange(row, startCol, 1, endCol - startCol + 1);
      range.clearDataValidations();
      if (type === 'binary') {
        range.insertCheckboxes();
      } else if (type === 'scale') {
        const rule = SpreadsheetApp.newDataValidation()
          .requireValueInList(listScale, false)
          .setAllowInvalid(true)
          .build();
        range.setDataValidation(rule);
      } else {
        const rule = SpreadsheetApp.newDataValidation()
          .requireValueInList(listTimeCount, false)
          .setAllowInvalid(true)
          .build();
        range.setDataValidation(rule);
      }
    });
  });
}

function seedDemoLogs() {
  const ss = SpreadsheetApp.getActive();
  const raw = ss.getSheetByName('raw_trackers');
  const logs = ss.getSheetByName('raw_tracker_logs');
  if (!raw || !logs) return;

  const trackerData = raw.getRange(2, 1, raw.getLastRow() - 1, 3).getValues();
  const trackers = trackerData.filter(r => r[0] && r[1] && r[2]);
  if (!trackers.length) return;

  logs.getRange(2, 1, Math.max(1, logs.getLastRow() - 1), 5).clearContent();

  const today = new Date();
  const start = new Date(today);
  start.setDate(start.getDate() - 29);

  const rows = [];
  const workoutDays = new Set();
  for (let d = new Date(start); d <= today; d.setDate(d.getDate() + 1)) {
    if ([1, 3, 5].includes(d.getDay())) workoutDays.add(dateKey(new Date(d)));
  }

  trackers.forEach(t => {
    const id = t[0];
    const name = String(t[1]).toLowerCase();
    const type = t[2];

    for (let d = new Date(start); d <= today; d.setDate(d.getDate() + 1)) {
      const day = new Date(d);
      let value = null;
      let partial = false;

      if (type === 'binary') {
        const roll = Math.random();
        if (roll < 0.1) {
          value = 0.5;
          partial = true;
        } else if (roll < 0.8) {
          value = 1;
        }
      } else if (type === 'time') {
        if (day.getDay() >= 1 && day.getDay() <= 5) {
          value = [1,2,3,4,5,6][Math.floor(Math.random()*6)];
        }
      } else if (type === 'count') {
        if (name.includes('тренир')) {
          if (workoutDays.has(dateKey(day))) value = 1;
        } else {
          value = [0,1,1,2,3][Math.floor(Math.random()*5)];
        }
      } else if (type === 'scale') {
        value = [4,5,6,7,8,9][Math.floor(Math.random()*6)];
      }

      if (value && value > 0) {
        rows.push([null, id, new Date(day), value, partial]);
      }
    }
  });

  if (rows.length) {
    logs.getRange(2, 1, rows.length, 5).setValues(rows);
  }
}

function refreshFromRaw() {
  const ss = SpreadsheetApp.getActive();
  const grid = ss.getSheetByName('Habits Tracker 2026');
  const raw = ss.getSheetByName('raw_trackers');
  const logs = ss.getSheetByName('raw_tracker_logs');
  if (!grid || !raw || !logs) return;

  const trackerData = raw.getRange(2, 1, raw.getLastRow() - 1, 3).getValues();
  const nameById = new Map();
  const typeById = new Map();
  trackerData.forEach(row => {
    if (row[0]) {
      nameById.set(String(row[0]), row[1]);
      typeById.set(String(row[0]), row[2]);
    }
  });

  const nameCol = 9; // I
  const startCol = 10; // J
  const endCol = 40; // AN

  const monthStarts = getMonthStartRows(grid);
  const rowMeta = new Map();
  monthStarts.forEach(startRow => {
    const dateRow = startRow - 2;
    const dateValues = grid.getRange(dateRow, startCol, 1, endCol - startCol + 1).getValues()[0];
    const colByDate = new Map();
    dateValues.forEach((val, idx) => {
      const key = dateKey(val);
      if (key) colByDate.set(key, startCol + idx);
    });

    for (let r = startRow; r < startRow + 20; r++) {
      const name = grid.getRange(r, nameCol).getValue();
      if (name) rowMeta.set(name, { row: r, colByDate });
    }
  });

  const logData = logs.getRange(2, 1, logs.getLastRow() - 1, 5).getValues();
  logData.forEach(row => {
    const trackerId = String(row[1]);
    const date = row[2];
    const value = row[3];
    if (!trackerId || !date) return;

    const name = nameById.get(trackerId);
    if (!name) return;

    const meta = rowMeta.get(name);
    if (!meta) return;

    const key = dateKey(date);
    if (!key) return;

    const col = meta.colByDate.get(key);
    if (!col) return;

    if (typeById.get(trackerId) === 'binary') {
      grid.getRange(meta.row, col).setValue(value >= 1);
    } else {
      grid.getRange(meta.row, col).setValue(value);
    }
  });
}

function onEdit(e) {
  const range = e.range;
  const sheet = range.getSheet();
  if (sheet.getName() !== 'Habits Tracker 2026') return;

  const row = range.getRow();
  const col = range.getColumn();
  if (row < 3 || col < 10 || col > 40) return;

  const ss = SpreadsheetApp.getActive();
  const raw = ss.getSheetByName('raw_trackers');
  const logs = ss.getSheetByName('raw_tracker_logs');
  if (!raw || !logs) return;

  const trackerName = sheet.getRange(row, 9).getValue();
  if (!trackerName) return;

  const trackerData = raw.getRange(2, 1, raw.getLastRow() - 1, 3).getValues();
  let trackerId = null;
  let trackerType = null;
  trackerData.forEach(r => {
    if (r[1] === trackerName) {
      trackerId = r[0];
      trackerType = r[2];
    }
  });
  if (!trackerId) return;

  const monthStarts = getMonthStartRows(sheet);
  let dateRow = null;
  for (let i = 0; i < monthStarts.length; i++) {
    if (row >= monthStarts[i] && row < monthStarts[i] + 20) {
      dateRow = monthStarts[i] - 2;
      break;
    }
  }
  if (!dateRow) return;

  const date = sheet.getRange(dateRow, col).getValue();
  const key = dateKey(date);
  if (!key) return;

  let value = range.getValue();
  if (value === '' || value === null) {
    const data = logs.getRange(2, 1, logs.getLastRow() - 1, 5).getValues();
    for (let i = data.length - 1; i >= 0; i--) {
      const rowData = data[i];
      if (rowData[1] == trackerId && dateKey(rowData[2]) === key) {
        logs.deleteRow(i + 2);
      }
    }
    return;
  }

  if (trackerType === 'binary') {
    value = value === true ? 1 : 0;
  }

  logs.appendRow([null, trackerId, new Date(date), value, false]);
}
