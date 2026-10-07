(() => {
  'use strict';
  const form = document.getElementById('asset-add');
  if (!form) return;
  const byId = id => document.getElementById(id);
  const field = name => form.elements.namedItem(name);
  const settings = byId('number-settings'), search = byId('an-search');
  const results = byId('an-results'), status = byId('an-search-status');
  const preview = byId('number-preview-result'), parts = byId('an-number-parts');
  const series = JSON.parse(byId('an-series').textContent);
  let searchTimer, previewTimer, searchRequest, previewRequest, searchVersion = 0, previewVersion = 0;
  const auto = () => field('number_mode').value === 'auto';
  function resetPreview(message='เลือกรายการด้านบนก่อน') {
    clearTimeout(previewTimer); previewVersion++; previewRequest?.abort();
    preview.textContent = message; parts.textContent = '';
    preview.parentElement.classList.remove('is-error');
  }
  function validateChoice() {
    search.setCustomValidity(auto() && !['catalog','existing','custom'].includes(field('number_choice').value)
      ? 'เลือกรายการจากผลการค้นหา หรือใช้รหัสที่โรงเรียนกำหนด' : '');
  }
  function formatSettings() {
    const saved = series.find(s => s.prefix === field('number_prefix').value.trim());
    if (saved) {
      field('number_digits').value = saved.digits;
      field('number_reset').value = saved.reset ? 'yearly' : 'continuous';
      field('number_append').value = saved.append ? 'yes' : 'no';
    }
    ['number_digits','number_reset','number_append'].forEach(name => field(name).disabled = !auto() || !!saved);
    byId('an-format-note').textContent = saved
      ? 'ชุดรหัสนี้ใช้รูปแบบที่โรงเรียนบันทึกไว้แล้ว ปรับปีหรือเลขเริ่มต้นได้'
      : 'ตั้งครั้งแรกได้ ระบบจะจำรูปแบบไว้กับชุดรหัสนี้';
    byId('an-year').disabled = !auto();
    byId('an-year').parentElement.hidden = field('number_append').value === 'no';
  }
  async function updatePreview() {
    if (!auto()) return;
    const prefix = field('number_prefix').value.trim();
    if (!prefix || !field('number_choice').value) { resetPreview(); return; }
    if (field('number_choice').value === 'custom' && !field('number_label').value.trim()) {
      resetPreview('ตั้งชื่อชุดรหัสและกรอกรหัสของโรงเรียน'); return;
    }
    const version = ++previewVersion;
    previewRequest?.abort(); previewRequest = new AbortController();
    preview.textContent = 'กำลังตรวจเลขถัดไป…'; parts.textContent = '';
    const query = new URLSearchParams();
    settings.querySelectorAll('[name]').forEach(el => query.set(el.name, el.value));
    try {
      const response = await fetch('/assets/number-preview?' + query, {signal:previewRequest.signal});
      const data = await response.json();
      if (version !== previewVersion || !auto()) return;
      if (!response.ok) throw new Error(data.detail || 'ตรวจเลขไม่สำเร็จ');
      preview.textContent = data.code; preview.parentElement.classList.remove('is-error');
      const suffix = data.code.slice(data.prefix.length + 1).split('/');
      parts.textContent = `รหัสจำแนก ${data.prefix} · เลขประจำชิ้น ${suffix[0]}` + (suffix[1] ? ` · ปี ${suffix[1]}` : '');
    } catch (error) {
      if (error.name === 'AbortError' || version !== previewVersion) return;
      preview.textContent = error.message || 'ตรวจเลขไม่สำเร็จ ลองใหม่อีกครั้ง';
      preview.parentElement.classList.add('is-error');
    }
  }
  function queuePreview() {
    resetPreview('กำลังตรวจเลขถัดไป…');
    previewTimer = setTimeout(updatePreview, 250);
  }
  function clearSelection() {
    field('number_choice').value = ''; field('number_prefix').value = ''; field('number_catalog_id').value = '';
    byId('an-selected').hidden = true; byId('an-search-box').hidden = false; byId('an-custom').hidden = true;
    byId('an-custom-name').required = false; byId('an-custom-code').required = false;
    field('number_digits').value = '4'; field('number_reset').value = 'yearly'; field('number_append').value = 'yes';
    field('number_start').value = '1';
    formatSettings(); resetPreview(); validateChoice();
  }
  function select(row) {
    searchVersion++; searchRequest?.abort(); clearTimeout(searchTimer);
    clearSelection();
    field('number_choice').value = row.kind; field('number_prefix').value = row.code;
    field('number_catalog_id').value = row.kind === 'catalog' ? row.id : '';
    byId('an-selected-name').textContent = row.name;
    byId('an-selected-code').textContent = `${row.code} · ${row.kind === 'existing' ? 'ชุดรหัสของโรงเรียน' : 'รหัสประเภทและชนิดตามคู่มือ'}`;
    byId('an-selected').hidden = false; byId('an-search-box').hidden = true; results.hidden = true;
    const source = byId('an-source'); source.hidden = !row.page;
    if (row.page) source.href = status.dataset.source + '#page=' + row.page;
    if (!field('name').value.trim() && row.name !== 'ชุดรหัสเดิมของโรงเรียน') field('name').value = row.name;
    validateChoice(); formatSettings(); updatePreview();
  }
  async function find() {
    if (!auto() || field('number_choice').value === 'custom') return;
    const version = ++searchVersion;
    searchRequest?.abort(); searchRequest = new AbortController();
    status.textContent = 'กำลังค้นหา…';
    try {
      const response = await fetch('/assets/catalog-search?q=' + encodeURIComponent(search.value.trim()), {signal:searchRequest.signal});
      if (!response.ok) throw new Error('ค้นหาไม่สำเร็จ ลองกดค้นหาอีกครั้ง');
      const data = await response.json();
      if (version !== searchVersion || !auto()) return;
      results.replaceChildren(); status.dataset.source = data.source_url;
      for (const row of data.items) {
        const button = document.createElement('button'); button.type = 'button'; button.className = 'an-result';
        const left = document.createElement('span'), name = document.createElement('span'), meta = document.createElement('small');
        name.textContent = row.name;
        meta.textContent = row.ambiguous ? 'รหัสซ้ำกับอีกชนิดในต้นฉบับ กรุณาตรวจคู่มือก่อนใช้'
          : row.kind === 'existing' ? 'ใช้รูปแบบเดิมของโรงเรียน' : `จากคู่มือ · หน้า PDF ${row.page}`;
        left.append(name, meta);
        const code = document.createElement('span'); code.className='an-result-code'; code.textContent=row.code;
        button.append(left,code); button.disabled=!!row.ambiguous;
        button.addEventListener('click',()=>select(row)); results.append(button);
        if (row.ambiguous) {
          const link=document.createElement('a'); link.className='an-help';link.style.padding='0 14px';
          link.href=data.source_url+'#page='+row.page;link.target='_blank';link.rel='noopener';link.textContent='เปิดหน้าต้นฉบับ ↗';results.append(link);
        }
      }
      results.hidden = !data.items.length;
      status.textContent = data.total ? `พบ ${data.total} รายการ` + (data.total>data.items.length ? ` · แสดง ${data.items.length} รายการแรก เพิ่มคำค้นเพื่อเจาะจงชนิด` : '')
        : 'ไม่พบรายการ ลองค้นด้วยชนิด เช่น ตู้ โต๊ะ เครื่องพิมพ์ หรือใช้รหัสที่โรงเรียนกำหนด';
    } catch (error) {
      if (error.name==='AbortError' || version!==searchVersion) return;
      status.textContent=error.message; results.hidden=true;
    }
  }
  function modeChanged() {
    settings.hidden=!auto(); byId('number-manual').hidden=auto();
    settings.querySelectorAll('input,select,button').forEach(el=>el.disabled=!auto());
    byId('new-asset-code').disabled=auto();
    byId('an-custom-name').required=byId('an-custom-code').required=auto() && field('number_choice').value==='custom';
    searchVersion++; searchRequest?.abort(); resetPreview(); validateChoice(); formatSettings();
    if (auto()) { if(field('number_prefix').value)updatePreview(); else find(); }
  }
  form.querySelectorAll('[name=number_mode]').forEach(el=>el.addEventListener('change',modeChanged));
  search.addEventListener('input',()=>{clearSelection();clearTimeout(searchTimer);searchVersion++;searchRequest?.abort();searchTimer=setTimeout(find,250);});
  search.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();clearTimeout(searchTimer);find();}});
  byId('an-search-button').addEventListener('click',()=>{clearTimeout(searchTimer);find();});
  byId('an-change').addEventListener('click',()=>{clearSelection();search.focus();find();});
  byId('an-custom-toggle').addEventListener('click',()=>{
    if(field('number_choice').value==='custom'){clearSelection();find();return;}
    clearSelection();searchVersion++;searchRequest?.abort();
    field('number_choice').value='custom';byId('an-custom').hidden=false;byId('an-search-box').hidden=true;
    byId('an-custom-name').required=byId('an-custom-code').required=true;
    field('number_prefix').value=byId('an-custom-code').value.trim();
    validateChoice();formatSettings();queuePreview();byId('an-custom-name').focus();
  });
  byId('an-custom-code').addEventListener('input',()=>{field('number_prefix').value=byId('an-custom-code').value.trim();formatSettings();queuePreview();});
  settings.addEventListener('input',e=>{if(e.target.matches('[name]') && !e.target.matches('[type=hidden]'))queuePreview();});
  field('number_append').addEventListener('change',()=>{formatSettings();queuePreview();});
  form.addEventListener('submit',e=>{validateChoice();if(!form.checkValidity()){e.preventDefault();e.stopImmediatePropagation();form.reportValidity();}},true);
  modeChanged();
})();
