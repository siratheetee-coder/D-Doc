/* Presentation only: the existing allocation endpoint remains authoritative. */
document.querySelectorAll('[data-project-funding]').forEach(function (form) {
  var fields = Array.from(form.querySelectorAll('[data-funding-amount]'));
  var target = Math.round(Number(form.dataset.fundingTarget) * 100);
  var totalNode = form.querySelector('[data-funding-total]');
  var statusNode = form.querySelector('[data-funding-status]');
  var save = form.querySelector('[data-funding-save]');
  function cents(field) { return Math.round(Number(field.value || 0) * 100); }
  function money(value) { return (value / 100).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}); }
  function refresh() {
    var total = fields.reduce(function (sum, field) { return sum + cents(field); }, 0);
    var invalid = fields.some(function (field) { return field.validity.badInput || (field.value !== '' && !field.validity.valid) || !Number.isFinite(cents(field)); });
    var over = total > target;
    totalNode.textContent = money(total);
    statusNode.classList.toggle('pf-invalid', invalid || over);
    statusNode.classList.toggle('pf-complete', !invalid && !over && total === target);
    if (invalid) statusNode.textContent = 'ตรวจจำนวนเงินในแต่ละรายการ ต้องไม่เกินวงเงินที่เลือกใช้ได้';
    else if (over) statusNode.textContent = 'ยอดที่กรอกเกินเงินของโครงการ ' + money(total - target) + ' บาท กรุณาปรับก่อนบันทึก';
    else if (total === target) statusNode.textContent = 'ระบุรายการเงินครบแล้ว';
    else statusNode.textContent = 'ยังไม่ระบุรายการเงินอีก ' + money(target - total) + ' บาท — บันทึกเท่าที่ทราบก่อนได้';
    save.disabled = invalid || over;
    form.querySelectorAll('[data-funding-fill]').forEach(function (button) {
      var field = button.parentElement.querySelector('[data-funding-amount]');
      button.disabled = invalid || total >= target || cents(field) >= Math.round(Number(field.max) * 100);
    });
  }
  fields.forEach(function (field) {
    field.addEventListener('input', refresh);
    field.addEventListener('blur', function () { if (field.value === '' && !field.validity.badInput) field.value = '0'; refresh(); });
  });
  form.querySelectorAll('[data-funding-fill]').forEach(function (button) {
    button.addEventListener('click', function () {
      var field = button.parentElement.querySelector('[data-funding-amount]');
      var others = fields.filter(function (f) { return f !== field; }).reduce(function (sum, f) { return sum + cents(f); }, 0);
      var fill = Math.max(0, Math.min(target - others, Math.round(Number(field.max) * 100)));
      field.value = (fill / 100).toFixed(2);
      field.classList.add('pf-filled');
      refresh();
    });
  });
  form.addEventListener('submit', function (event) {
    fields.forEach(function (field) { if (field.value === '' && !field.validity.badInput) field.value = '0'; });
    refresh(); if (save.disabled) event.preventDefault();
  });
  refresh();
});
