<?php

namespace App\Filament\Resources;

use App\Filament\Resources\CodeResource\Pages;
use App\Models\Code;
use Filament\Forms;
use Filament\Forms\Form;
use Filament\Resources\Resource;
use Filament\Tables;
use Filament\Tables\Table;
use Illuminate\Database\Eloquent\Builder;
use Illuminate\Database\Eloquent\SoftDeletingScope;

class CodeResource extends Resource
{
    protected static ?string $model = Code::class;

    protected static ?string $navigationIcon = 'heroicon-o-code-bracket';
    protected static ?string $modelLabel = '코드';
    protected static ?string $pluralModelLabel = '코드';
    protected static ?string $navigationGroup = '관리';
    protected static ?int $navigationSort = 4;

    public static function form(Form $form): Form
    {
        return $form
            ->schema([
                Forms\Components\Select::make('type')
                    ->label('차종구분')
                    ->options([
                        'ev' => '전기차',
                        'ice' => '내연기관',
                    ])
                    ->required(),
                Forms\Components\TextInput::make('code')
                    ->label('고장코드')
                    ->required()
                    ->maxLength(255),
                Forms\Components\TextInput::make('unit_name')
                    ->label('유니트명')
                    ->required()
                    ->maxLength(255),
                Forms\Components\TextInput::make('unit_type')
                    ->label('유니트구분')
                    ->required()
                    ->maxLength(255),
                Forms\Components\TextInput::make('desc')
                    ->label('설명')
                    ->required()
                    ->maxLength(255),
                Forms\Components\Textarea::make('detail_desc')
                    ->label('상세설명')
                    ->required()
                    ->columnSpanFull(),
                Forms\Components\Textarea::make('root_cause')
                    ->label('주요원인')
                    ->required()
                    ->columnSpanFull(),
                Forms\Components\Textarea::make('howto_fix1')
                    ->label('조치방법1')
                    ->required()
                    ->columnSpanFull(),
                Forms\Components\Textarea::make('howto_fix2')
                    ->label('조치방법2')
                    ->columnSpanFull(),
                Forms\Components\Textarea::make('howto_fix3')
                    ->label('조치방법3')
                    ->columnSpanFull(),
            ]);
    }

    public static function table(Table $table): Table
    {
        return $table
            ->columns([
                Tables\Columns\TextColumn::make('type')
                    ->label('차종구분')
                    ->badge()
                    ->color(fn (string $state): string => match ($state) {
                        'ev' => 'success',
                        'ice' => 'warning',
                    }),
                Tables\Columns\TextColumn::make('code')
                    ->label('고장코드')
                    ->searchable(),
                Tables\Columns\TextColumn::make('unit_name')
                    ->label('유니트명')
                    ->searchable(),
                Tables\Columns\TextColumn::make('unit_type')
                    ->label('유니트구분')
                    ->searchable(),
                Tables\Columns\TextColumn::make('desc')
                    ->label('설명')
                    ->searchable()
                    ->limit(50),
                Tables\Columns\TextColumn::make('created_at')
                    ->label('생성일')
                    ->dateTime('Y-m-d H:i:s')
                    ->sortable(),
            ])
            ->filters([
                //
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

    public static function getRelations(): array
    {
        return [
            //
        ];
    }

    public static function getPages(): array
    {
        return [
            'index' => Pages\ListCodes::route('/'),
            'create' => Pages\CreateCode::route('/create'),
            'edit' => Pages\EditCode::route('/{record}/edit'),
        ];
    }
}
