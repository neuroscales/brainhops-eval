'use strict';
function filterCases() {
  const search = (document.querySelector('#search')?.value || '').toLowerCase();
  const status = document.querySelector('#status')?.value || '';
  const family = document.querySelector('#family')?.value || '';
  let count = 0;
  let total = 0;
  document.querySelectorAll('[data-case-status]').forEach(element => {
    const text = element.dataset.caseSearch || element.textContent.toLowerCase();
    element.hidden = Boolean(
      (status && element.dataset.caseStatus !== status) ||
      (family && element.dataset.family !== family) || !text.includes(search)
    );
    if (element.tagName === 'TR') {
      total++;
      if (!element.hidden) count++;
    }
  });
  const label = document.querySelector('#visible-count');
  if (label) label.textContent = `${count} of ${total} cases shown · filters also apply to images`;
}
document.querySelectorAll('#search,#status,#family').forEach(element => {
  element.addEventListener('input', filterCases);
});
filterCases();
