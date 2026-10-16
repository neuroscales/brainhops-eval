'use strict';
function filterCases(){
 const search=(document.querySelector('#search')?.value||'').toLowerCase();
 const status=document.querySelector('#status')?.value||'';
 const family=document.querySelector('#family')?.value||'';
 let count=0;
 document.querySelectorAll('tr[data-case-status]').forEach(row=>{
  row.hidden=Boolean((status&&row.dataset.caseStatus!==status)||(family&&row.dataset.family!==family)||!row.textContent.toLowerCase().includes(search));
  if(!row.hidden)count++;
 });
 const label=document.querySelector('#visible-count');
 if(label)label.textContent=`${count} cases shown`;
}
document.querySelectorAll('#search,#status,#family').forEach(el=>el.addEventListener('input',filterCases));
filterCases();
