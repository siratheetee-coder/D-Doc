document.querySelectorAll('[data-project-funding]').forEach(function (form) {
  var status = form.querySelector('[data-funding-status]');
  form.addEventListener('change', function () {
    status.textContent = 'เลือก ' + form.querySelectorAll('input[type=checkbox]:checked').length + ' รายการ · กดบันทึกเพื่อยืนยัน';
  });
});
