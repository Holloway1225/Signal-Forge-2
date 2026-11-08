const $ = id => document.getElementById(id);
let audioMode = false;
const defaultBackend = location.hostname === 'localhost' || location.hostname === '127.0.0.1' ? 'http://localhost:8000' : '';
$('backend').value = localStorage.getItem('signalForgeBackend') || defaultBackend;
$('backend').addEventListener('change', () => localStorage.setItem('signalForgeBackend', $('backend').value.trim().replace(/\/$/, '')));
for (const name of ['intensity', 'atmosphere']) $(name).addEventListener('input', () => $(name + 'Value').textContent = $(name).value);
function setMode(value) {audioMode = value; $('refFields').hidden = value; $('audioFields').hidden = !value; $('refTab').classList.toggle('active', !value); $('audioTab').classList.toggle('active', value);}
$('refTab').onclick = () => setMode(false); $('audioTab').onclick = () => setMode(true);
function getSettings() {return {notes:$('notes').value.trim(), vocals:$('vocals').value, intensity:Number($('intensity').value), atmosphere:Number($('atmosphere').value), mode:$('cryptid').checked?'cryptid':'neutral'};}
function display(data) {
  $('results').hidden = false;
  $('stylePrompt').textContent = data.style_prompt || '';
  $('count').textContent = `${(data.style_prompt || '').length} / 1000 characters`;
  const tags = data.section_tags || {};
  $('tags').textContent = Object.entries(tags).map(([name, tag]) => `${name.replaceAll('_',' ').toUpperCase()}: ${tag}`).join('\n\n');
  $('analysis').replaceChildren();
  for (const [name, value] of Object.entries(data.analysis || {})) {const p=document.createElement('p');const strong=document.createElement('strong');strong.textContent=name.replaceAll('_',' ') + ': ';p.append(strong, document.createTextNode(typeof value === 'string'?value:JSON.stringify(value)));$('analysis').append(p);}
  $('caveat').textContent = data.caveat || '';
  $('results').scrollIntoView({behavior:'smooth',block:'start'});
}
$('generate').onclick = async () => {
  const base = $('backend').value.trim().replace(/\/$/, '');
  if (!/^https?:\/\//.test(base)) {$('status').textContent='Enter your deployed backend URL at the bottom of the page.';return;}
  const settings = getSettings();
  let path='/api/generate', options={method:'POST'};
  if (audioMode) {
    const file=$('audio').files[0];if(!file){$('status').textContent='Choose an audio file.';return;}
    if(file.size>12*1024*1024){$('status').textContent='File must be 12 MB or smaller.';return;}
    const form=new FormData();form.append('audio',file);Object.entries(settings).forEach(([k,v])=>form.append(k,String(v)));options.body=form;path='/api/analyze-audio';
  } else {
    if (!$('song').value.trim() && !settings.notes){$('status').textContent='Enter a song title or sound description.';return;}
    options.headers={'Content-Type':'application/json'};options.body=JSON.stringify({...settings,song:$('song').value.trim(),artist:$('artist').value.trim()});
  }
  $('generate').disabled=true;$('status').textContent='Processing signal…';
  try {const response=await fetch(base+path,options);const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'Request failed');display(data);$('status').textContent='Signal generated.';}
  catch(err){$('status').textContent=`Error: ${err.message}`;}
  finally{$('generate').disabled=false;}
};
async function copyText(text){try{await navigator.clipboard.writeText(text);$('status').textContent='Copied.';}catch{$('status').textContent='Copy unavailable; select the text manually.';}}
$('copyStyle').onclick=()=>copyText($('stylePrompt').textContent);
$('copyTags').onclick=()=>copyText($('tags').textContent);
