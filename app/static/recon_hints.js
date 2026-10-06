/* ตัวช่วยตอนงบกระทบยอดไม่ตรง
   รับผลต่างกับรายการที่มีอยู่จริง แล้วเดาว่าน่าจะพลาดตรงไหน
   คืนเป็นรายการข้อความสั้น ๆ ไม่แก้ตัวเลขให้เอง คนตรวจต้องเป็นคนตัดสิน */
(function (root) {
  'use strict';

  var EPS = 0.005;

  function baht(n) {
    return n.toLocaleString('th-TH', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  }

  function near(a, b) {
    return Math.abs(a - b) < EPS;
  }

  function thaiDate(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || '');
    return m ? Number(m[3]) + '/' + m[2] + '/' + (Number(m[1]) + 543) : (iso || '');
  }

  function label(item) {
    var who = item.payee || item.note || item.ref || 'ไม่ระบุชื่อ';
    var no = item.no ? ' เลขที่ ' + item.no : '';
    var on = item.on ? ' วันที่ ' + thaiDate(item.on) : '';
    return who + no + on;
  }

  /* diff = ฝั่งธนาคาร ลบ ฝั่งโรงเรียน
     บวก = ฝั่งธนาคารสูงกว่า แปลว่ายังหักไม่ครบ หรือฝั่งโรงเรียนยังบันทึกรับไม่ครบ
     ลบ  = ฝั่งธนาคารต่ำกว่า แปลว่าหักเกิน หรือฝั่งโรงเรียนบันทึกรับเกิน */
  function reconHints(input) {
    var diff = Math.round((input.diff || 0) * 100) / 100;
    var out = [];
    if (Math.abs(diff) < EPS) return out;
    var size = Math.abs(diff);
    var checks = input.checks || [];
    var txns = input.txns || [];
    var loose = input.looseSum || 0;

    if (loose > 0 && near(loose, size)) {
      out.push({kind: 'loose', text: 'ผลต่างเท่ากับยอดรายการจ่ายที่ยังไม่ได้ระบุบัญชีพอดี ('
        + baht(loose) + ' บาท) ไปใส่บัญชีให้ครบในทะเบียนคุมการจ่ายเงินก่อน'});
    }

    checks.forEach(function (c) {
      if (near(c.amount, size)) {
        out.push({kind: 'check', text: 'ผลต่างเท่ากับรายการจ่าย ' + baht(c.amount) + ' บาท พอดี · '
          + label(c) + (c.cleared ? ' (ติ๊กว่าเงินออกแล้ว ลองตรวจวันที่เงินออก)'
                                  : ' (ยังไม่ติ๊กว่าเงินออก ลองตรวจว่านับเป็นรายการคงค้างแล้วหรือยัง)')});
      } else if (near(c.amount * 2, size)) {
        out.push({kind: 'check2', text: 'ผลต่างเป็นสองเท่าของรายการจ่าย ' + baht(c.amount)
          + ' บาท (' + label(c) + ') มักเกิดจากใส่ผิดฝั่ง บวกแทนที่จะหัก'});
      }
    });

    txns.forEach(function (t) {
      if (near(t.amount, size)) {
        out.push({kind: 'txn', text: 'ผลต่างเท่ากับรายการ' + (t.kind === 'in' ? 'รับ' : 'จ่าย')
          + 'เงิน ' + baht(t.amount) + ' บาท พอดี · ' + label(t)
          + ' ลองตรวจว่าลงทะเบียนคุมตรงกับที่ธนาคารตัดจริงไหม'});
      }
    });

    /* เลขสลับหลัก เช่น ลง 1,260 แทน 1,620 ผลต่างจะหารด้วย 9 ลงตัวเสมอ
       เป็นเคล็ดเก่าของคนทำบัญชี ใช้ได้ผลจริงกับการพิมพ์ตัวเลขสลับ */
    if (out.length === 0 && size >= 9 && near(size % 9, 0)) {
      out.push({kind: 'transpose', text: 'ผลต่าง ' + baht(size)
        + ' บาท หารด้วย 9 ลงตัว มักเกิดจากพิมพ์ตัวเลขสลับหลัก เช่น ลง 1,260 แทน 1,620'});
    }

    if (out.length === 0) {
      out.push({kind: 'none', text: diff > 0
        ? 'ฝั่งธนาคารสูงกว่า ' + baht(size)
          + ' บาท ลองดูว่ามีเงินเข้าบัญชีที่ยังไม่ได้ลงทะเบียนคุม หรือหักรายการคงค้างยังไม่ครบ'
        : 'ฝั่งโรงเรียนสูงกว่า ' + baht(size)
          + ' บาท ลองดูว่ามีรายการจ่ายที่ลงทะเบียนคุมไว้แต่ธนาคารตัดไปแล้ว หรือหักรายการคงค้างซ้ำ'});
    }
    return out.slice(0, 6);
  }

  root.reconHints = reconHints;
  if (typeof module !== 'undefined' && module.exports) module.exports = reconHints;
})(typeof window !== 'undefined' ? window : globalThis);
