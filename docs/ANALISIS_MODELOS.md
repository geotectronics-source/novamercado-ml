# Análisis de los datos y comparación de modelos alternativos

Objetivo: saber si otro modelo de machine learning reduciría el **costo de las cantidades
sugeridas**, que es lo que se evalúa. Todos los candidatos se compararon con el **mismo
protocolo** que usa producción: 4 cortes, calibración fuera de muestra y validación de 28 días
(`scripts/comparar_modelos.py`; resultados en `evidencia/comparacion_modelos.csv`).

## 1. Qué dicen los datos

| Hallazgo | Medición | Implicación para el modelo |
|---|---|---|
| Ruido **multiplicativo** | El CV del residuo es casi constante (0,25–0,29) en todos los niveles de venta | Conviene modelar en escala relativa o logarítmica (lo hace el cociente actual) |
| **Sobredispersión** | Varianza/media del residuo de 2 a 54 (Poisson = 1) | Una pérdida Poisson no describe bien el ruido |
| Día de la semana **distinto por tipo de tienda** | Hiper y súper venden más el sábado (+27–32 %); las express venden **menos** el fin de semana (sábado −10 %, domingo −30 %) | Hacen falta interacciones tipo × día |
| Día de la semana **distinto por familia** | Licores +42 % el viernes y +57 % el sábado; carnes +33 % el sábado | Interacciones familia × día |
| Promociones **saturantes** | De 0 a 1–2 productos en promoción, la venta pasa de 0,85 a 1,02 del promedio; después crece despacio | Efecto no lineal (≈ logarítmico) |
| Días de **pago** | Día 15: +14 %; último día del mes: +36 % | Variables de día del mes |
| Feriados | Feriado −17 %; fecha comercial +15 %; día de pago +22 %; medio día (24 y 31 de diciembre) ×2,07 | Variables de feriados por ciudad |
| Tendencia | +4 % a +8 % anual por tienda | Necesita adaptarse al nivel (los árboles no extrapolan) |
| **Poca memoria** día a día | Autocorrelación del residuo: 0,14 a 1 día, 0,02 a 7 días | Los rezagos cortos aportan poco |
| **Choque común tienda-día** | Correlación media de 0,37 entre los residuos de las 12 familias de una tienda en el mismo día | Hay un componente (afluencia del día) que **no se puede conocer** al pronosticar |

**Conclusión del análisis:** la estructura es multiplicativa y está dominada por efectos de
calendario, promoción y nivel, que el modelo actual ya captura. Una parte importante del
error restante es ruido no predecible (el choque común tienda-día), así que el margen de
mejora en el pronóstico puntual es pequeño.

## 2. Candidatos evaluados

| Modelo | Idea | Por qué probarlo |
|---|---|---|
| `lightgbm_cociente` (actual) | LightGBM, pérdida L2 sobre ventas / nivel reciente | Referencia |
| `lightgbm_tweedie` | Igual, con pérdida Tweedie p = 1,9 (casi Gamma, enlace log) | Diseñada para ruido multiplicativo y sobredisperso |
| `loglineal_ridge` | Regresión log-lineal regularizada (GLM multiplicativo) con interacciones explícitas: tipo × familia × día, día del mes × tipo, promoción (log) por familia, feriados por familia, mes por familia | Reproduce la estructura multiplicativa encontrada y, al ser lineal, sí extrapola |
| `ensamble` | Promedio geométrico de LightGBM actual y log-lineal | Combina dos modelos de naturaleza distinta |
| `lightgbm_costo` | Segundo booster con pérdida pinball de τ por familia, ponderada por (c_f + c_s): minimiza **directamente** el costo | Optimizar la métrica de negocio en lugar de la media |
| `lightgbm_cuantil` | LightGBM con objetivo `quantile` nativo, un modelo por τ | Cuantiles condicionales |

## 3. Resultados (costo total en la validación de 28 días; menor es mejor)

| Modelo | 2025-06-30 | 2025-09-30 | 2025-12-31 | 2026-02-28 | **Promedio** | vs. actual |
|---|---:|---:|---:|---:|---:|---:|
| **lightgbm_cociente (actual)** | 87 544 | **88 298** | 118 684 | 89 947 | **96 118** | — |
| ensamble | 88 985 | 93 210 | **116 626** | **89 109** | 96 983 | +0,9 % |
| lightgbm_tweedie | 90 530 | 88 609 | 122 664 | 89 397 | 97 800 | +1,7 % |
| loglineal_ridge | 95 956 | 104 862 | 121 186 | 92 449 | 103 613 | +7,8 % |
| lightgbm_costo | 98 769 | 105 379 | 137 208 | 99 463 | 110 205 | +14,7 % |
| lightgbm_cuantil (acotado) | 96 541 | 123 692 | 130 912 | 110 072 | 115 304 | +20,0 % |
| baseline_estacional | 101 222 | 102 038 | 167 089 | 112 023 | 120 593 | +25,5 % |

Lecciones:

* **Ningún candidato supera al modelo actual en promedio.** Confirma la conclusión del análisis:
  el error restante es sobre todo ruido no predecible.
* **El ensamble gana en los dos cortes más difíciles o recientes** (diciembre y febrero de 2026)
  y queda a solo 0,9 % en promedio: es el mejor *retador*.
* El log-lineal solo es peor (+7,8 %) y además sobrestima en 4 % en el último corte (la
  corrección de sesgo log-normal es imperfecta), pero aporta diversidad al ensamble.
* **Optimizar directamente el costo salió peor** que media + multiplicador:
  - La pérdida pinball personalizada converge mal en LightGBM porque no reajusta las hojas al cuantil.
  - El objetivo `quantile` nativo es **inestable en τ extremos**: con licores (τ = 0,95) llegó a
    sugerir 90 veces la venta esperada sin una cota de sanidad.
  - Como el ruido es multiplicativo con CV casi constante, un multiplicador por familia × tipo de
    tienda ya es casi el cuantil óptimo, y es mucho más estable.

## 4. Recomendación (implementada)

1. **Mantener `lightgbm_cociente` como modelo principal candidato.** Es el mejor en promedio, el
   más rápido (3 s) y el más simple de operar.
2. **Agregar el `ensamble` (LightGBM + log-lineal) como retador** en cada reentrenamiento. Su
   atractivo es la **robustez ante cambios de demanda**: la parte lineal extrapola efectos
   (promociones, niveles) que los árboles no pueden. Costo: unos 4 s más por entrenamiento y
   scikit-learn como dependencia nueva.

   **Implementado:** `ModeloLogLineal` y `ModeloEnsamble` en `src/novamercado/modelo.py`. En
   `entrenamiento.entrenar_candidatos` compiten baseline, LightGBM y ensamble; se registra como
   versión el de menor costo en validación, y el criterio de reemplazo (mejora ≥ 1 % frente al
   vigente) decide si se promueve. Con los datos publicados, el primer modelo es el ensamble
   (89 109 frente a 89 947 de LightGBM en la validación de febrero de 2026).
3. No se recomienda la optimización directa del costo con LightGBM por la inestabilidad
   observada; si se quisiera explorar, la alternativa más prometedora es un modelo de
   distribución explícita (p. ej. binomial negativa con enlace log), cuyos cuantiles salen de
   forma analítica.

Para reproducir:

```bash
pip install scikit-learn==1.5.2 scipy==1.17.1
python scripts/comparar_modelos.py datos
```
