<?php

namespace App\Filament\Resources\ScanResource\RelationManagers;

use App\Enums\ScanType;
use Filament\Forms;
use Filament\Forms\Form;
use Filament\Resources\RelationManagers\RelationManager;
use Filament\Tables;
use Filament\Tables\Table;
use Illuminate\Database\Eloquent\Builder;
use Illuminate\Database\Eloquent\SoftDeletingScope;

class ScanCodesRelationManager extends RelationManager
{
    protected static string $relationship = 'scanCodes';

    protected static ?string $title = '스캔 코드';
    protected static ?string $modelLabel = '스캔 코드';
    protected static ?string $pluralModelLabel = '스캔 코드';

    public function form(Form $form): Form
    {
        return $form
            ->schema([
                Forms\Components\Select::make('type')
                    ->label('유형')
                    ->options(ScanType::options())
                    ->required(),
                Forms\Components\Select::make('code_id')
                    ->relationship('code', 'code')
                    ->label('코드')
                    ->searchable()
                    ->preload()
                    ->required()
                    ->getOptionLabelFromRecordUsing(fn ($record) => "{$record->code} - {$record->desc}")
                    ->searchable(['code', 'desc', 'unit_name'])
                    ->live()
                    ->afterStateUpdated(function ($state, Forms\Set $set) {
                        if ($state) {
                            $code = \App\Models\Code::find($state);
                            if ($code) {
                                $set('desc', $code->desc);
                                $set('root_cause', $code->root_cause);
                                $set('howto_fix1', $code->howto_fix1);
                                $set('howto_fix2', $code->howto_fix2);
                                $set('howto_fix3', $code->howto_fix3);
                            }
                        }
                    }),
                Forms\Components\TextInput::make('desc')
                    ->label('설명')
                    ->disabled()
                    ->dehydrated(false)
                    ->formatStateUsing(fn ($record) => $record?->code?->desc),
                Forms\Components\Textarea::make('root_cause')
                    ->label('주요원인')
                    ->disabled()
                    ->dehydrated(false)
                    ->formatStateUsing(fn ($record) => $record?->code?->root_cause),
                Forms\Components\Textarea::make('howto_fix1')
                    ->label('조치방법 1')
                    ->disabled()
                    ->dehydrated(false)
                    ->formatStateUsing(fn ($record) => $record?->code?->howto_fix1),
                Forms\Components\Textarea::make('howto_fix2')
                    ->label('조치방법 2')
                    ->disabled()
                    ->dehydrated(false)
                    ->formatStateUsing(fn ($record) => $record?->code?->howto_fix2),
                Forms\Components\Textarea::make('howto_fix3')
                    ->label('조치방법 3')
                    ->disabled()
                    ->dehydrated(false)
                    ->formatStateUsing(fn ($record) => $record?->code?->howto_fix3),
            ]);
    }

    public function table(Table $table): Table
    {
        return $table
            ->columns([
                Tables\Columns\TextColumn::make('type')
                    ->label('유형')
                    ->badge()
                    ->formatStateUsing(fn (string $state): string => ScanType::from($state)->label())
                    ->sortable()
                    ->color(fn (string $state): string => ScanType::from($state)->color()),
                Tables\Columns\TextColumn::make('code.code')
                    ->label('고장코드')
                    ->searchable(),
                Tables\Columns\TextColumn::make('code.unit_name')
                    ->label('유니트명')
                    ->searchable(),
                Tables\Columns\TextColumn::make('code.unit_type')
                    ->label('유니트구분')
                    ->searchable(),
                Tables\Columns\TextColumn::make('code.desc')
                    ->label('설명')
                    ->searchable()
                    ->limit(50),
                Tables\Columns\TextColumn::make('code.root_cause')
                    ->label('주요원인')
                    ->searchable()
                    ->limit(50),
            ])
            ->filters([
                //
            ])
            ->headerActions([
                Tables\Actions\CreateAction::make(),
            ])
            ->actions([
                Tables\Actions\EditAction::make(),
                Tables\Actions\DeleteAction::make(),
            ])
            ->bulkActions([
                Tables\Actions\BulkActionGroup::make([
                    Tables\Actions\DeleteBulkAction::make(),
                ]),
            ]);
    }
}
