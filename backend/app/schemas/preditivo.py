from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.models.enums import TipoEvento


class OcorrenciaIn(BaseModel):
    categoria: str = Field(examples=["ACIDENTE"])
    gravidade: int | None = Field(None, ge=1, le=4, description="1 (leve) a 4 (grave). Sem valor: a da categoria")
    lon: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)
    inicio_em: datetime | None = None
    fim_em: datetime | None = None
    descricao: str | None = Field(None, max_length=500)


class EventoCidadeIn(BaseModel):
    nome: str = Field(min_length=2, max_length=160)
    tipo: TipoEvento
    local_nome: str | None = Field(None, max_length=160)
    lon: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)
    inicio_em: datetime
    fim_em: datetime
    publico_estimado: int = Field(0, ge=0)
    raio_influencia_m: int = Field(2000, ge=100, le=20000)

    @model_validator(mode="after")
    def _periodo(self):
        if self.fim_em <= self.inicio_em:
            raise ValueError("O fim do evento precisa ser depois do início.")
        return self


class ClimaEdicaoIn(BaseModel):
    """Muda a previsão de todas as horas entre inicio e fim. Campos vazios ficam como estão."""

    inicio: datetime
    fim: datetime
    chuva_mm: float | None = Field(None, ge=0, le=200, description="Chuva por hora (mm). Forte: 10 ou mais")
    temperatura_c: float | None = Field(None, ge=-5, le=45)
    alerta_tempestade: bool | None = None

    @model_validator(mode="after")
    def _periodo(self):
        if self.fim <= self.inicio:
            raise ValueError("O fim precisa ser depois do início.")
        if (self.fim - self.inicio).total_seconds() > 7 * 86400:
            raise ValueError("A previsão editável cobre no máximo 7 dias.")
        if self.chuva_mm is None and self.temperatura_c is None and self.alerta_tempestade is None:
            raise ValueError("Informe ao menos chuva, temperatura ou alerta de tempestade.")
        return self
