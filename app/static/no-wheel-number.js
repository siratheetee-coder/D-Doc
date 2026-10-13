// ช่องตัวเลข (input type=number) ที่กำลังพิมพ์อยู่: เบราว์เซอร์จะเพิ่ม/ลดค่าเองเมื่อหมุนล้อเมาส์
// ผู้ใช้เผลอเลื่อนหน้าแล้วยอดเงิน/จำนวนเปลี่ยนโดยไม่รู้ตัว คำนวณผิด (เจ้าของขอให้ตัดทั้งระบบ)
// วิธี: หมุนล้อบนช่องที่โฟกัสอยู่ = เอาโฟกัสออกก่อน ค่าจึงไม่เปลี่ยน และหน้ายังเลื่อนได้ตามปกติ
// (ไม่ใช้ preventDefault เพราะจะทำให้หน้าเลื่อนไม่ได้ตอนเมาส์อยู่บนช่อง)
(function () {
  document.addEventListener('wheel', function (e) {
    var el = document.activeElement;
    if (el && el.tagName === 'INPUT' && el.type === 'number' && (el === e.target || el.contains(e.target))) {
      el.blur();
    }
  }, { passive: true, capture: true });
})();
