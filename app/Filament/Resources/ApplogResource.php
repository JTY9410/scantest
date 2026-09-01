<?php

namespace App\Filament\Resources;

use App\Filament\Resources\ApplogResource\Pages;
use App\Filament\Resources\ApplogResource\RelationManagers;
use App\Models\Applog;
use Filament\Forms;
use Filament\Forms\Form;
use Filament\Resources\Resource;
use Filament\Tables;
use Filament\Tables\Table;
use Illuminate\Database\Eloquent\Builder;
use Illuminate\Database\Eloquent\Model;

class ApplogResource extends Resource
{
    protected static ?string $model = Applog::class;

    protected static ?string $navigationIcon = 'heroicon-o-document-text';

    protected static ?string $navigationGroup = '시스템';

    protected static ?int $navigationSort = 3;

    protected static ?string $modelLabel = '앱 로그';

    protected static ?string $pluralModelLabel = '앱 로그';

    public static function form(Form $form): Form
    {
        return $form
            ->schema([
                Forms\Components\TextInput::make('type')
                    ->label('로그 타입')
                    ->required()
                    ->maxLength(255),
                Forms\Components\TextInput::make('message')
                    ->label('로그 메시지')
                    ->required()
                    ->maxLength(255),
                Forms\Components\Textarea::make('desc')
                    ->label('추가 텍스트')
                    ->nullable()
                    ->columnSpanFull(),
                Forms\Components\DateTimePicker::make('timestamp')
                    ->label('로그 발생 시간')
                    ->required(),
                Forms\Components\Select::make('user_id')
                    ->label('회원')
                    ->relationship('user', 'name')
                    ->searchable()
                    ->preload()
                    ->nullable(),
                Forms\Components\TextInput::make('user_tid')
                    ->label('회원 TID')
                    ->nullable()
                    ->maxLength(255),
            ]);
    }

    public static function table(Table $table): Table
    {
        return $table
            ->columns([
                Tables\Columns\TextColumn::make('timestamp')
                    ->label('타임스탬프')
                    ->dateTime('Y-m-d H:i:s.u')
                    ->sortable(),
                Tables\Columns\TextColumn::make('user.id')
                    ->label('회원')
                    ->searchable(),
                Tables\Columns\TextColumn::make('user.tid')
                    ->label('회원 TID')
                    ->searchable(),
                Tables\Columns\TextColumn::make('type')
                    ->label('로그 타입')
                    ->searchable(),
                Tables\Columns\TextColumn::make('message')
                    ->label('로그 메시지')
                    ->searchable(),
                Tables\Columns\TextColumn::make('desc')
                    ->label('추가 텍스트')
                    ->searchable(),
                Tables\Columns\TextColumn::make('created_at')
                    ->dateTime('Y-m-d H:i:s')
                    ->label('생성일')
                    ->sortable(),
            ])
            ->defaultSort('created_at', 'desc')
            ->filters([
                Tables\Filters\SelectFilter::make('type')
                    ->label('로그 타입')
                    ->options(fn () => Applog::query()->distinct()->pluck('type', 'type')->toArray()),
                Tables\Filters\SelectFilter::make('user_id')
                    ->label('회원')
                    ->relationship('user', 'name'),
            ])
            ->actions([
                Tables\Actions\ViewAction::make(),
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
            'index' => Pages\ListApplogs::route('/'),
        ];
    }

    public static function getEloquentQuery(): Builder
    {
        return parent::getEloquentQuery()->latest();
    }

    public static function canCreate(): bool
    {
        return false;
    }

    public static function canEdit(Model $record): bool
    {
        return false;
    }
}
