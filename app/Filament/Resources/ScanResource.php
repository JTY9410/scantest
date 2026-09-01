<?php

namespace App\Filament\Resources;

use App\Filament\Resources\ScanResource\Pages;
use App\Filament\Resources\ScanResource\RelationManagers;
use App\Models\Scan;
use Filament\Forms;
use Filament\Forms\Form;
use Filament\Resources\Resource;
use Filament\Tables;
use Filament\Tables\Table;
use Illuminate\Database\Eloquent\Builder;
use Illuminate\Database\Eloquent\SoftDeletingScope;
use App\Enums\ScanType;

class ScanResource extends Resource
{
    protected static ?string $model = Scan::class;

    protected static ?string $navigationIcon = 'heroicon-o-qr-code';
    protected static ?string $modelLabel = '스캔';
    protected static ?string $pluralModelLabel = '스캔';
    protected static ?string $navigationGroup = '관리';
    protected static ?int $navigationSort = 2;

    public static function form(Form $form): Form
    {
        return $form
            ->schema([
                Forms\Components\Select::make('company_id')
                    ->relationship('company', 'name')
                    ->label('회사')
                    ->searchable()
                    ->preload(),
                Forms\Components\Select::make('tester_id')
                    ->relationship('tester', 'name')
                    ->label('테스터')
                    ->searchable()
                    ->preload()
                    ->required(),
                Forms\Components\Select::make('owner_id')
                    ->relationship('owner', 'name')
                    ->label('소유자')
                    ->searchable()
                    ->preload(),
                Forms\Components\Select::make('type')
                    ->label('유형')
                    ->options(ScanType::options())
                    ->required(),
                Forms\Components\TextInput::make('device_type')
                    ->label('장치 유형')
                    ->required()
                    ->maxLength(255),
                Forms\Components\TextInput::make('device_uid')
                    ->label('장치 UID')
                    ->required()
                    ->maxLength(255),
                Forms\Components\TextInput::make('scan_vin')
                    ->label('스캔 VIN')
                    ->required()
                    ->maxLength(255),
                Forms\Components\TextInput::make('car_no')
                    ->label('차량번호')
                    ->maxLength(255),
                Forms\Components\TextInput::make('car_vin')
                    ->label('차대번호')
                    ->maxLength(255),
                Forms\Components\TextInput::make('car_maker')
                    ->label('제조사')
                    ->maxLength(255),
                Forms\Components\TextInput::make('car_model')
                    ->label('차량모델')
                    ->maxLength(255),
                Forms\Components\TextInput::make('car_submodel')
                    ->label('서브모델')
                    ->maxLength(255),
                Forms\Components\TextInput::make('car_cc')
                    ->label('배기량')
                    ->maxLength(255),
                Forms\Components\TextInput::make('car_year')
                    ->label('연식')
                    ->maxLength(255),
                Forms\Components\TextInput::make('car_fuel')
                    ->label('연료')
                    ->maxLength(255),
                Forms\Components\TextInput::make('car_battery_capacity')
                    ->label('배터리 용량')
                    ->maxLength(255),
                Forms\Components\TextInput::make('car_discharge_energy')
                    ->label('방전 에너지')
                    ->maxLength(255),
                Forms\Components\TextInput::make('car_charge_energy')
                    ->label('충전 에너지')
                    ->maxLength(255),
                Forms\Components\TextInput::make('car_distance')
                    ->label('주행거리 (km)')
                    ->numeric()
                    ->maxLength(255),
                Forms\Components\Textarea::make('raw')
                    ->label('원본 데이터')
                    ->columnSpanFull()
                    ->rows(10)
                    ->formatStateUsing(fn ($state) => is_array($state) ? json_encode($state, JSON_PRETTY_PRINT) : $state)
                    ->dehydrateStateUsing(fn ($state) => is_string($state) ? json_decode($state, true) : $state),
                Forms\Components\Textarea::make('bms_data')
                    ->label('BMS 데이터')
                    ->columnSpanFull()
                    ->rows(10)
                    ->formatStateUsing(fn ($state) => is_array($state) ? json_encode($state, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE) : $state)
                    ->dehydrateStateUsing(fn ($state) => is_string($state) ? json_decode($state, true) : $state),
            ]);
    }

    public static function table(Table $table): Table
    {
        return $table
            ->columns([
                Tables\Columns\TextColumn::make('company.name')
                    ->label('회사')
                    ->sortable()
                    ->searchable(),
                Tables\Columns\TextColumn::make('tester.name')
                    ->label('테스터')
                    ->sortable()
                    ->searchable(),
                Tables\Columns\TextColumn::make('type')
                    ->label('유형')
                    ->badge()
                    ->formatStateUsing(fn (ScanType $state): string => "{$state->code()} - {$state->label()}")
                    ->sortable()
                    ->color(fn (ScanType $state): string => $state->color()),
                Tables\Columns\TextColumn::make('device_type')
                    ->label('장치 유형')
                    ->searchable(),
                Tables\Columns\TextColumn::make('device_uid')
                    ->label('장치 UID')
                    ->searchable(),
                Tables\Columns\TextColumn::make('scan_vin')
                    ->label('스캔 VIN')
                    ->searchable(),
                Tables\Columns\TextColumn::make('car_no')
                    ->label('차량번호')
                    ->searchable(),
                Tables\Columns\TextColumn::make('car_vin')
                    ->label('차대번호')
                    ->searchable(),
                Tables\Columns\TextColumn::make('car_maker')
                    ->label('제조사')
                    ->searchable(),
                Tables\Columns\TextColumn::make('car_model')
                    ->label('차량모델')
                    ->searchable(),
                Tables\Columns\TextColumn::make('car_submodel')
                    ->label('서브모델')
                    ->searchable()
                    ->toggleable(isToggledHiddenByDefault: true),
                Tables\Columns\TextColumn::make('car_distance')
                    ->label('주행거리 (km)')
                    ->numeric()
                    ->sortable(),
                Tables\Columns\TextColumn::make('created_at')
                    ->label('생성일')
                    ->dateTime('Y-m-d H:i:s')
                    ->sortable(),
            ])
            ->filters([
                Tables\Filters\SelectFilter::make('company')
                    ->label('회사')
                    ->relationship('company', 'name'),
                Tables\Filters\SelectFilter::make('tester')
                    ->label('테스터')
                    ->relationship('tester', 'name'),
            ])
            ->actions([
                Tables\Actions\ViewAction::make(),
                Tables\Actions\EditAction::make(),
                Tables\Actions\DeleteAction::make(),
            ])
            ->bulkActions([
                Tables\Actions\BulkActionGroup::make([
                    Tables\Actions\DeleteBulkAction::make(),
                ]),
            ]);
    }

    public static function getRelations(): array
    {
        return [
            RelationManagers\ScanCodesRelationManager::make(),
        ];
    }

    public static function getPages(): array
    {
        return [
            'index' => Pages\ListScans::route('/'),
            'create' => Pages\CreateScan::route('/create'),
            'edit' => Pages\EditScan::route('/{record}/edit'),
        ];
    }
}
