from django import forms


class BuscarRespaldosForm(forms.Form):
    desde = forms.DateField(
        label='Desde', required=False, input_formats=['%Y-%m-%d'],
        widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date', 'class': 'form-control'}),
    )
    hasta = forms.DateField(
        label='Hasta', required=False, input_formats=['%Y-%m-%d'],
        widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date', 'class': 'form-control'}),
    )

    def clean(self):
        datos = super().clean()
        desde, hasta = datos.get('desde'), datos.get('hasta')
        if desde and hasta and desde > hasta:
            raise forms.ValidationError('La fecha Desde no puede ser posterior a la fecha Hasta.')
        return datos
