- SAM decides Active as usual. Muse answers yes / no / unsure in VlmState a few seconds later.
- VlmState "no" means Muse thinks the detection is not a real person. Active stays as SAM
  decided; SCADA can use VlmState to suppress a nuisance alarm or ask an operator to look.
- Muse can be wrong in poor light; "unsure" is a valid answer and is not a Clear.
