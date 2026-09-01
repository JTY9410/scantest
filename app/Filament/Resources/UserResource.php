<?php

namespace App\Filament\Resources;

use App\Enums\UserType;
use App\Filament\Resources\UserResource\Pages;
use App\Filament\Resources\UserResource\RelationManagers;
use App\Models\User;
use Filament\Forms;
use Filament\Forms\Form;
use Filament\Resources\Resource;
use Filament\Tables;
use Filament\Tables\Table;
use Illuminate\Database\Eloquent\Builder;
use Illuminate\Database\Eloquent\SoftDeletingScope;
use Illuminate\Support\Facades\Hash;
use Filament\Notifications\Notification;

class UserResource extends Resource
{
    protected static ?string $model = User::class;

    protected static ?string $navigationIcon = 'heroicon-o-users';
    protected static ?string $modelLabel = '사용자';
    protected static ?string $pluralModelLabel = '사용자';
    protected static ?string $navigationGroup = '관리';
    protected static ?int $navigationSort = 1;

    public static function form(Form $form): Form
    {
        return $form
            ->schema([
                Forms\Components\Select::make('company_id')
                    ->relationship('company', 'name')
                    ->label('회사')
                    ->searchable()
                    ->preload()
                    ->nullable(),
                Forms\Components\Select::make('type')
                    ->label('유형')
                    ->options(UserType::options())
                    ->required(),
                Forms\Components\TextInput::make('name')
                    ->label('이름')
                    ->required()
                    ->maxLength(255),
                Forms\Components\TextInput::make('mobile')
                    ->label('휴대전화')
                    ->tel()
                    ->nullable(),
                Forms\Components\TextInput::make('biz_no')
                    ->label('사업자등록번호')
                    ->nullable(),
                Forms\Components\TextInput::make('tid')
                    ->label('로그인 아이디')
                    ->required()
                    ->unique(ignoreRecord: true)
                    ->maxLength(255),
                Forms\Components\TextInput::make('email')
                    ->label('이메일')
                    ->email()
                    ->nullable()
                    ->unique(ignoreRecord: true)
                    ->maxLength(255),
                Forms\Components\TextInput::make('password')
                    ->label('비밀번호')
                    ->password()
                    // ->dehydrateStateUsing(fn ($state) => Hash::make($state))
                    ->dehydrated(fn ($state) => filled($state))
                    ->required(fn (string $context): bool => $context === 'create'),

                Forms\Components\Section::make('API 접근 설정')
                    ->schema([
                        Forms\Components\TextInput::make('api_key')
                            ->label('API 키')
                            ->disabled()
                            ->dehydrated(false)
                            ->suffixAction(
                                Forms\Components\Actions\Action::make('copyApiKey')
                                    ->icon('heroicon-o-clipboard')
                                    ->color('gray')
                                    ->action(fn () => null)
                            )
                            ->visible(fn ($record) => $record && $record->api_key),

                        Forms\Components\Placeholder::make('api_actions')
                            ->label('')
                            ->content(fn ($record) => new \Illuminate\Support\HtmlString(
                                '<div class="flex gap-2">' .
                                ($record && !$record->api_key
                                    ? '<span class="text-sm text-gray-500">API 키가 생성되지 않았습니다. 생성 버튼을 클릭하세요.</span>'
                                    : '<span class="text-sm text-gray-500">API 키를 재생성하려면 재생성 버튼을 클릭하세요.</span>'
                                ) .
                                '</div>'
                            ))
                            ->visible(fn ($record) => $record !== null),

                        Forms\Components\Textarea::make('api_host')
                            ->label('허용 IP 주소')
                            ->placeholder('192.168.1.1, 10.0.0.*, *')
                            ->helperText('쉼표로 구분하여 입력하세요. *는 모든 IP를 허용합니다.')
                            ->rows(3),

                        Forms\Components\DateTimePicker::make('api_expires_at')
                            ->label('만료일')
                            ->helperText('비워두면 만료일이 없습니다.')
                            ->nullable(),
                    ])
                    ->collapsed()
                    ->visible(fn ($context) => $context === 'edit')
                    ->headerActions([
                        Forms\Components\Actions\Action::make('generateApiKey')
                            ->label('API 키 생성')
                            ->icon('heroicon-o-key')
                            ->requiresConfirmation()
                            ->modalHeading('API 키 생성')
                            ->modalDescription('새로운 API 키를 생성하시겠습니까?')
                            ->action(function (User $record, Forms\Set $set) {
                                $apiKey = User::generateApiKey();
                                $record->api_key = $apiKey;
                                $record->save();

                                $set('api_key', $apiKey);

                                Notification::make()
                                    ->success()
                                    ->title('API 키가 생성되었습니다')
                                    ->body('페이지를 새로고침하여 변경사항을 확인하세요.')
                                    ->send();
                            })
                            ->visible(fn ($record) => $record && !$record->api_key),

                        Forms\Components\Actions\Action::make('regenerateApiKey')
                            ->label('API 키 재생성')
                            ->icon('heroicon-o-arrow-path')
                            ->color('danger')
                            ->requiresConfirmation()
                            ->modalHeading('API 키 재생성')
                            ->modalDescription('기존 API 키는 더 이상 사용할 수 없게 됩니다. 계속하시겠습니까?')
                            ->action(function (User $record, Forms\Set $set) {
                                $apiKey = User::generateApiKey();
                                $record->api_key = $apiKey;
                                $record->save();

                                $set('api_key', $apiKey);

                                Notification::make()
                                    ->warning()
                                    ->title('API 키가 재생성되었습니다')
                                    ->body('페이지를 새로고침하여 변경사항을 확인하세요.')
                                    ->send();
                            })
                            ->visible(fn ($record) => $record && $record->api_key),
                    ]),
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
                Tables\Columns\TextColumn::make('type')
                    ->label('유형')
                    ->badge()
                    ->formatStateUsing(fn (string $state): string => UserType::from($state)->label())
                    ->sortable(),
                Tables\Columns\TextColumn::make('name')
                    ->label('이름')
                    ->searchable(),
                Tables\Columns\TextColumn::make('mobile')
                    ->label('휴대전화')
                    ->searchable(),
                Tables\Columns\TextColumn::make('biz_no')
                    ->label('사업자등록번호')
                    ->searchable(),
                Tables\Columns\TextColumn::make('tid')
                    ->label('로그인 아이디')
                    ->searchable(),
                Tables\Columns\TextColumn::make('email')
                    ->label('이메일')
                    ->searchable(),
                Tables\Columns\TextColumn::make('api_key')
                    ->label('API 상태')
                    ->badge()
                    ->getStateUsing(fn (User $record) =>
                        $record->api_key
                            ? ($record->isApiKeyExpired() ? '만료' : '활성')
                            : '미생성'
                    )
                    ->color(fn (string $state) => match($state) {
                        '활성' => 'success',
                        '만료' => 'danger',
                        '미생성' => 'gray',
                    })
                    ->toggleable(),
                Tables\Columns\TextColumn::make('api_expires_at')
                    ->label('API 키 만료일')
                    ->dateTime('Y-m-d H:i')
                    ->sortable()
                    ->toggleable(isToggledHiddenByDefault: true),
                Tables\Columns\TextColumn::make('created_at')
                    ->label('생성일')
                    ->dateTime('Y-m-d H:i:s')
                    ->sortable()
                    ->toggleable(isToggledHiddenByDefault: true),
                Tables\Columns\TextColumn::make('updated_at')
                    ->label('수정일')
                    ->dateTime('Y-m-d H:i:s')
                    ->sortable()
                    ->toggleable(isToggledHiddenByDefault: true),
            ])
            ->filters([
                Tables\Filters\SelectFilter::make('type')
                    ->label('유형')
                    ->options(UserType::options()),
                Tables\Filters\SelectFilter::make('company')
                    ->label('회사')
                    ->relationship('company', 'name'),
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
            'index' => Pages\ListUsers::route('/'),
            'create' => Pages\CreateUser::route('/create'),
            'edit' => Pages\EditUser::route('/{record}/edit'),
        ];
    }
}
